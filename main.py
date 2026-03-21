import pandas as pd
from datetime import datetime
from langgraph.graph import StateGraph, END
import os
from source.news_finder import monitor_signals
from agents.intent_classifier import classify_signal, generate_email
from agents.contact_finder import find_linkedin_contact, load_cache, save_cache, find_contact_email
from typing import TypedDict, List, Dict, Optional


# ---------------------------
# Graph State
# ---------------------------

class LeadState(TypedDict):
    signals: List[Dict]
    current_signal: Optional[Dict]
    intent_result: Optional[object]
    contact: Optional[Dict]
    email_draft: Optional[Dict]       # {"subject": ..., "body": ...}
    leads: List[Dict]


# ---------------------------
# STEP 1 — Fetch Signals
# ---------------------------

def fetch_signals(state: LeadState):
    try:
        signals = monitor_signals()
        print(f"📡 Fetched {len(signals)} signals")
    except Exception as e:
        print(f"❌ Signal fetch failed: {e}")
        signals = []

    return {
        "signals": signals,
        "leads": []
    }


# ---------------------------
# STEP 2 — Get Next Signal
# ---------------------------

def get_next_signal(state: LeadState):
    signals = state.get("signals", [])

    if not signals:
        # Do NOT reset leads here — preserve accumulated leads list
        return {
            "current_signal": None,
            "signals": [],
            "intent_result": None,
            "contact": None,
            "email_draft": None
        }

    return {
        # Do NOT include leads key here — omitting it preserves existing value in state
        "current_signal": signals[0],
        "signals": signals[1:],
        "intent_result": None,
        "contact": None,
        "email_draft": None
    }


def next_signal_router(state: LeadState):
    if not state.get("signals") and state.get("current_signal") is None:
        return "export_excel"
    if not state.get("current_signal"):
        return "export_excel"
    return "classify"


# ---------------------------
# STEP 3 — LLM Classification
# ---------------------------

def classify(state: LeadState):
    signal = state["current_signal"]

    text = f"""
    Title: {signal['Title']}
    Summary: {signal['Summary']}
    """

    try:
        result = classify_signal(text)
    except Exception as e:
        print(f"❌ Classification error: {e}")
        result = None

    return {"intent_result": result}


def intent_router(state: LeadState):
    result = state.get("intent_result")

    if result is None:
        return "skip"

    if result.intent == "YES":
        return "find_contact"

    return "skip"


# ---------------------------
# STEP 4 — Find Contact
# ---------------------------

CONTACT_CACHE = load_cache()


def find_contact(state: LeadState):
    result = state.get("intent_result")
    company = getattr(result, "company_name", "").strip().lower()

    if not company or company == "unknown":
        print("⚠️ No valid company name, skipping contact search")
        return {"contact": {}}

    # Cache hit
    if company in CONTACT_CACHE:
        print(f"✅ Cache hit for: {company}")
        return {"contact": CONTACT_CACHE[company]}

    # Find LinkedIn contact
    try:
        contact = find_linkedin_contact(company)
    except Exception as e:
        print(f"❌ LinkedIn search failed: {e}")
        contact = {"name": "Not Found", "title": "", "linkedin": "", "website": ""}

    # Find email via pattern + Hunter verification
    name = contact.get("name", "")
    website = contact.get("website", "")
    email, confidence = "", 0

    if name and name != "Not Found" and website and len(name.split()) >= 2:
        try:
            email, confidence = find_contact_email(name, website)
        except Exception as e:
            print(f"❌ Email lookup failed: {e}")

    full_contact = {
        **contact,
        "email": email,
        "confidence": confidence
    }

    # Persist to cache
    CONTACT_CACHE[company] = full_contact
    save_cache(CONTACT_CACHE)

    return {"contact": full_contact}


# ---------------------------
# STEP 5 — Generate Email
# ---------------------------

# Always generate email after finding contact — no confidence gate.
# Even low-confidence emails get a draft so the user can review and send manually.

def generate_email_node(state: LeadState):
    contact = state.get("contact", {})
    result = state.get("intent_result")

    company  = getattr(result, "company_name", "") or "Unknown Company"
    name     = contact.get("name", "") or "there"
    title    = contact.get("title", "") or "Leader"
    summary  = getattr(result, "signal_summary", "") or ""
    score    = getattr(result, "urgency", 0)

    lead_data = {
        "Company Name":   company,
        "Contact Name":   name,
        "Title":          title,
        "Signal Summary": summary,
        "Intent Score":   score
    }

    try:
        email_draft = generate_email(lead_data)
        print(f"📧 Email drafted for {name} @ {company}")
    except Exception as e:
        print(f"❌ Email generation failed: {e}")
        email_draft = {"subject": "", "body": ""}

    return {"email_draft": email_draft}


# ---------------------------
# STEP 6 — Save Lead
# ---------------------------

def save_lead(state: LeadState):
    contact = state.get("contact", {})
    signal = state.get("current_signal", {})
    result = state.get("intent_result")
    email_draft = state.get("email_draft") or {}

    lead = {
        "Company Name":       getattr(result, "company_name", "UNKNOWN"),
        "Contact Name":       contact.get("name", "Not Found"),
        "Title":              contact.get("title", ""),
        "LinkedIn URL":       contact.get("linkedin", ""),
        "Company Website":    contact.get("website", ""),
        "Email":              contact.get("email", ""),
        "Email Confidence":   contact.get("confidence", 0),
        "Email Subject":      email_draft.get("subject", ""),
        "Email Body":         email_draft.get("body", ""),
        "Signal Source":      signal.get("Link", ""),
        "Signal Summary":     getattr(result, "signal_summary", ""),
        "Intent Score":       getattr(result, "urgency", 0),
        "Date Found":         datetime.today().strftime("%Y-%m-%d")
    }

    # Copy the list — never mutate state directly in LangGraph.
    # Mutating in place means the graph sees the same object reference
    # and does not register it as a state update, silently dropping leads.
    existing_leads = list(state.get("leads") or [])
    existing_leads.append(lead)

    return {"leads": existing_leads}


# ---------------------------
# Skip node
# ---------------------------

def skip(state: LeadState):
    return state


# ---------------------------
# STEP 7 — Export Excel
# ---------------------------

def export_excel(state: LeadState):
    file_path = "data/leads.xlsx"

    if not state.get("leads"):
        print("ℹ️ No leads found this run")
        return state

    new_df = pd.DataFrame(state["leads"])

    try:
        os.makedirs("data", exist_ok=True)

        if os.path.exists(file_path):
            try:
                existing_df = pd.read_excel(file_path, engine="openpyxl")
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            except Exception as e:
                print(f"⚠️ Could not read existing Excel, overwriting: {e}")
                combined_df = new_df
        else:
            combined_df = new_df

        combined_df.drop_duplicates(
            subset=["Company Name", "Signal Summary"],
            keep="last",
            inplace=True
        )

        combined_df.to_excel(file_path, index=False, engine="openpyxl")
        print(f"✅ Excel saved. Total leads: {len(combined_df)}")

        # Sync state leads to exactly what was saved — this is what app.py reads.
        # Without this, state has pre-dedup leads while Excel has deduped leads,
        # causing the UI count to differ from Excel count.
        state["leads"] = combined_df.to_dict(orient="records")

    except Exception as e:
        print(f"❌ Excel export failed: {e}")
        try:
            new_df.to_excel(file_path, index=False, engine="openpyxl")
            print("✅ Fallback: saved new leads only")
        except Exception as e2:
            print(f"❌ Fallback Excel save also failed: {e2}")

    return state


# ---------------------------
# Build Graph
# ---------------------------

builder = StateGraph(LeadState)

builder.add_node("fetch_signals",     fetch_signals)
builder.add_node("get_next_signal",   get_next_signal)
builder.add_node("classify",          classify)
builder.add_node("find_contact",      find_contact)
builder.add_node("generate_email",    generate_email_node)
builder.add_node("save_lead",         save_lead)
builder.add_node("skip",              skip)
builder.add_node("export_excel",      export_excel)

builder.set_entry_point("fetch_signals")

builder.add_edge("fetch_signals", "get_next_signal")

builder.add_conditional_edges(
    "get_next_signal",
    next_signal_router,
    {
        "classify":     "classify",
        "export_excel": "export_excel"
    }
)

builder.add_conditional_edges(
    "classify",
    intent_router,
    {
        "find_contact": "find_contact",
        "skip":         "skip"
    }
)

# Always generate email after finding contact — no confidence gate
builder.add_edge("find_contact",   "generate_email")
builder.add_edge("generate_email", "save_lead")
builder.add_edge("save_lead",      "get_next_signal")
builder.add_edge("skip",           "get_next_signal")
builder.add_edge("export_excel",   END)

graph = builder.compile()


# ---------------------------
# Run
# ---------------------------

if __name__ == "__main__":
    result = graph.invoke({})
    print(f"\n✅ Pipeline complete. Leads found: {len(result.get('leads', []))}")