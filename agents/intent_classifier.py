import os
import re
import json
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

load_dotenv()

# ---------------------------
# LLM
# ---------------------------

llm = ChatGroq(
    model_name="llama-3.3-70b-versatile",
    groq_api_key=os.getenv("GROQ_API_KEY"),
    temperature=0
)


# ---------------------------
# Schema 1 — Intent Classification
#
# ROOT CAUSE of urgency crash:
# Groq validates tool-call JSON at the API level BEFORE returning the response.
# If urgency is "0" (string), Groq rejects it with a 400 error — Pydantic
# never even sees it, so field_validator never runs.
#
# FIX: Use `json_schema_extra` to tell Groq urgency is `number` (not `integer`).
# Groq accepts "0", 0, 0.0 all as valid `number`. Then field_validator
# coerces whatever comes back into a clean Python int.
# ---------------------------

class IntentSchema(BaseModel):
    intent: Literal["YES", "NO", "MAYBE"] = Field(
        description="YES = strong buying signal, MAYBE = weak signal, NO = irrelevant"
    )
    company_name: str = Field(
        description="Exact company name from the signal. UNKNOWN if no real company."
    )
    signal_summary: str = Field(
        description="One sentence summary of what the news is about."
    )
    reason: str = Field(
        description="Why this was classified this way in one sentence."
    )
    urgency: int = Field(
        description="Priority score 0-10. Return a number, not a string.",
        json_schema_extra={"type": "number", "minimum": 0, "maximum": 10}
    )

    @field_validator("urgency", mode="before")
    @classmethod
    def coerce_urgency(cls, v):
        """Coerce any LLM output form into a clean int."""
        if isinstance(v, (int, float)):
            return max(0, min(10, int(v)))
        if isinstance(v, str):
            m = re.search(r"\d+", v)
            return max(0, min(10, int(m.group()))) if m else 0
        return 0


structured_classifier = llm.with_structured_output(IntentSchema)

_NOISE_NAMES = {
    "realty+", "conclave", "awards", "summit", "conference",
    "expo", "forum", "association", "report", "unknown", "index",
    "symposia", "symposium", "show", "pulse"
}


def classify_signal(text: str) -> IntentSchema:
    prompt = f"""You are an AI that identifies PropTech buying signals for a B2B sales team.

COMPANY EXTRACTION RULES:
- Extract ONLY a real company name (e.g. Zillow, Aurum PropTech, NoBroker, OfficeBanao)
- Return UNKNOWN for: events, awards, conclaves, summits, reports, market research
- Return UNKNOWN if no specific company is the subject

INTENT RULES:
YES: funding raised, product launched, market expansion, acquisition, hiring surge, partnership
MAYBE: industry discussion, trend report, vague announcement
NO: event/conference, award ceremony, editorial, regulatory news without company

URGENCY — return a NUMBER (not string) 0 to 10:
9-10 = Major funding or acquisition
7-8  = Product launch, expansion, partnership
4-6  = Moderate signal, small funding
1-3  = Weak signal
0    = NO intent

NEWS SIGNAL:
{text}"""

    try:
        result = structured_classifier.invoke(prompt)
        if result.company_name.lower().strip() in _NOISE_NAMES:
            result.intent = "NO"
            result.company_name = "UNKNOWN"
        return result
    except Exception as e:
        print(f"❌ Classification error: {e}")
        return IntentSchema(
            intent="NO",
            company_name="UNKNOWN",
            signal_summary="Classification failed",
            reason="LLM error",
            urgency=0
        )


# ---------------------------
# Schema 2 — Email Generation
#
# ROOT CAUSE of email crash:
# The LLM writes the body with \n newlines inside JSON strings.
# Groq's tool-call validator rejects JSON with literal newlines in string values.
#
# FIX: Don't use structured output for email — use plain text generation
# and parse subject/body ourselves. Plain text has no JSON validation issues.
# ---------------------------

def generate_email(lead: dict) -> dict:
    """
    Generate outreach email using plain text (not structured output).
    Avoids Groq's tool-call JSON validation which rejects multiline strings.
    Parse subject and body from the LLM's plain text response.
    """

    first_name = lead.get("Contact Name", "there").split()[0]

    prompt = f"""Write a short cold outreach email for a B2B sales rep.

LEAD:
- Company: {lead['Company Name']}
- Contact: {first_name} ({lead.get('Title', 'Leader')})
- News: {lead['Signal Summary']}

RULES:
- First line: Subject: <subject line>
- Then blank line
- Then email body (under 100 words)
- Start body with "{first_name},"
- Reference the news naturally in first sentence
- End with asking for a 15-minute call
- No buzzwords, no placeholders, sound human

Output exactly:
Subject: <subject>

<body>"""

    try:
        response = llm.invoke(prompt)
        raw = response.content.strip()

        # Parse subject and body from plain text response
        subject = ""
        body    = ""

        lines = raw.split("\n")

        for i, line in enumerate(lines):
            if line.lower().startswith("subject:"):
                subject = line[8:].strip()
                # Body is everything after the subject line + blank line
                rest = "\n".join(lines[i+1:]).strip()
                body = rest
                break

        # Fallback if parsing fails
        if not subject:
            subject = f"Quick note on {lead['Company Name']}"
        if not body:
            body = raw

        return {"subject": subject, "body": body}

    except Exception as e:
        print(f"❌ Email generation error: {e}")
        return {"subject": "", "body": ""}