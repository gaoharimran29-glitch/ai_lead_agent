import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

from source.news_finder import monitor_signals
from agents.intent_classifier import classify_signal, generate_email
from agents.contact_finder import find_linkedin_contact, load_cache, save_cache, find_contact_email


# ---------------------------
# Contact Cache — loaded once at startup
# ---------------------------

CONTACT_CACHE = load_cache()


# ---------------------------
# Per-Signal Pipeline
# Processes one signal completely: classify → contact → email → lead dict
# This function runs in parallel across all signals.
# ---------------------------

def process_signal(signal: dict) -> dict | None:
    """
    Full pipeline for a single signal.
    Returns a lead dict if signal is YES, otherwise None.
    Runs independently — safe to call from multiple threads.
    """

    title   = signal.get("Title", "")
    summary = signal.get("Summary", "")

    print(f"\n⚡ Processing: {title[:60]}")

    # ── Step 1: Classify ──────────────────────────────────────────
    text   = f"Title: {title}\nSummary: {summary}"
    result = classify_signal(text)

    print(f"   Intent: {result.intent} | Company: {result.company_name} | Score: {result.urgency}")

    # Only continue for strong buying signals
    if result.intent != "YES" or result.company_name.upper() == "UNKNOWN":
        print(f"   ↩ Skipped ({result.intent})")
        return None

    company = result.company_name.strip().lower()

    # ── Step 2: Find Contact ──────────────────────────────────────
    # Check cache first — avoids redundant searches
    if company in CONTACT_CACHE:
        print(f"   ✅ Cache hit: {company}")
        contact = CONTACT_CACHE[company]
    else:
        try:
            contact = find_linkedin_contact(company)
        except Exception as e:
            print(f"   ❌ LinkedIn search failed: {e}")
            contact = {"name": "Not Found", "title": "", "linkedin": "", "website": ""}

        # Find email
        name    = contact.get("name", "")
        website = contact.get("website", "")
        email, confidence = "", 0

        if name and name != "Not Found" and website and len(name.split()) >= 2:
            try:
                email, confidence = find_contact_email(name, website)
            except Exception as e:
                print(f"   ❌ Email lookup failed: {e}")

        contact = {**contact, "email": email, "confidence": confidence}

        # Write to cache immediately so other threads benefit
        # Use a simple assignment — dict writes in CPython are thread-safe
        # for single key updates due to the GIL
        CONTACT_CACHE[company] = contact

    # ── Step 3: Generate Email ────────────────────────────────────
    lead_data = {
        "Company Name":   result.company_name,
        "Contact Name":   contact.get("name", "") or "there",
        "Title":          contact.get("title", "") or "Leader",
        "Signal Summary": result.signal_summary or "",
        "Intent Score":   result.urgency,
    }

    try:
        email_draft = generate_email(lead_data)
    except Exception as e:
        print(f"   ❌ Email generation failed: {e}")
        email_draft = {"subject": "", "body": ""}

    # ── Step 4: Build Lead Dict ───────────────────────────────────
    lead = {
        "Company Name":     result.company_name,
        "Contact Name":     contact.get("name", "Not Found"),
        "Title":            contact.get("title", ""),
        "LinkedIn URL":     contact.get("linkedin", ""),
        "Company Website":  contact.get("website", ""),
        "Email":            contact.get("email", ""),
        "Email Confidence": contact.get("confidence", 0),
        "Email Subject":    email_draft.get("subject", ""),
        "Email Body":       email_draft.get("body", ""),
        "Signal Source":    signal.get("Link", ""),
        "Signal Summary":   result.signal_summary,
        "Intent Score":     result.urgency,
        "Date Found":       datetime.today().strftime("%Y-%m-%d"),
    }

    print(f"   ✅ Lead saved: {result.company_name}")
    return lead


# ---------------------------
# Excel Export
# ---------------------------

def export_to_excel(leads: list) -> list:
    """
    Merge new leads with existing Excel, deduplicate, save.
    Returns the final deduped list (what the UI will display).
    """
    file_path = "data/leads.xlsx"

    if not leads:
        print("ℹ️ No leads to export")
        return []

    new_df = pd.DataFrame(leads)

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
        print(f"✅ Excel saved — {len(combined_df)} total leads")

        records = combined_df.to_dict(orient="records")

        # Sanitize NaN — pandas converts empty Excel cells to float NaN.
        # Any NaN in string fields renders as "nan" in the UI text areas.
        import math
        def clean(v):
            if isinstance(v, float) and math.isnan(v):
                return ""
            return v

        records = [{k: clean(v) for k, v in row.items()} for row in records]

        return records

    except Exception as e:
        print(f"❌ Excel export failed: {e}")
        try:
            new_df.to_excel(file_path, index=False, engine="openpyxl")
            print("✅ Fallback: saved new leads only")
        except Exception as e2:
            print(f"❌ Fallback also failed: {e2}")

    return leads


# ---------------------------
# Main Pipeline — Parallel
# ---------------------------

def run_pipeline() -> dict:
    """
    Full pipeline with parallel signal processing.

    Old approach: sequential LangGraph loop
      Signal 1 → classify → contact → email → save
      Signal 2 → classify → contact → email → save   ← waits for Signal 1
      ...

    New approach: ThreadPoolExecutor
      Signal 1 ─┐
      Signal 2 ─┼─ all run at the same time → collect results → export
      Signal 3 ─┘

    Each signal is independent — no shared mutable state between threads
    except CONTACT_CACHE which uses single-key dict writes (GIL-safe).

    Workers = min(signals, 5) to avoid hammering APIs.
    """

    # ── Fetch all signals ─────────────────────────────────────────
    try:
        signals = monitor_signals()
        print(f"\n📡 Fetched {len(signals)} signals")
    except Exception as e:
        print(f"❌ Signal fetch failed: {e}")
        return {"leads": []}

    if not signals:
        print("ℹ️ No signals found")
        return {"leads": []}

    # ── Parallel processing ───────────────────────────────────────
    leads      = []
    workers    = min(len(signals), 5)   # cap at 5 to respect API rate limits

    print(f"🚀 Processing {len(signals)} signals in parallel (workers: {workers})\n")

    with ThreadPoolExecutor(max_workers=workers) as executor:

        # Submit all signals at once
        future_to_signal = {
            executor.submit(process_signal, signal): signal
            for signal in signals
        }

        # Collect results as they complete
        for future in as_completed(future_to_signal):
            signal = future_to_signal[future]
            try:
                lead = future.result()
                if lead is not None:
                    leads.append(lead)
            except Exception as e:
                print(f"❌ Signal processing crashed: {signal.get('Title', '')[:40]} — {e}")

    print(f"\n📊 {len(leads)} YES leads found from {len(signals)} signals")

    # ── Persist cache after all threads finish ────────────────────
    save_cache(CONTACT_CACHE)

    # ── Export to Excel ───────────────────────────────────────────
    final_leads = export_to_excel(leads)

    return {"leads": final_leads}


# ---------------------------
# LangGraph-compatible wrapper
# app.py calls graph.invoke({}) — keep that interface working
# ---------------------------

class _FakeGraph:
    """
    Thin wrapper so app.py can keep calling graph.invoke({})
    without any changes.
    """
    def invoke(self, _state: dict) -> dict:
        return run_pipeline()


graph = _FakeGraph()


# ---------------------------
# Run directly
# ---------------------------

if __name__ == "__main__":
    result = run_pipeline()
    print(f"\n✅ Pipeline complete. Leads: {len(result.get('leads', []))}")