import os
import sys
from typing import Literal
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()

current_dir = os.path.dirname(os.path.abspath(__file__)) #gives current directory filepath
project_root = os.path.dirname(current_dir) #gives root folder name

if project_root not in sys.path:
    sys.path.append(project_root) #add root folder to path if folder not in python paths

try:
    from source.news_finder import monitor_signals
    print("✅ Successfully imported news_finder from source folder")
except ImportError as e:
    print(f"❌ ImportError: {e}")
    sys.exit(1)


# ---------------------------
# Intent Schema (For enforcing the schema to LLM output)
# ---------------------------
class IntentSchema(BaseModel):
    """Information about a PropTech buying signal."""

    intent: Literal["YES", "NO", "MAYBE"] = Field(description="Classification of the signal")

    company_name: str = Field(description="Exact company name mentioned in the signal. Return UNKNOWN if no company.")

    signal_summary: str = Field(description="Short summary of the news")

    reason: str = Field(description="Why the signal was classified this way")

    urgency: int = Field(ge=0,le=10, description="Priority score from 1 (low) to 10 (high)")

# ---------------------------
# Initialize LLM
# ---------------------------
llm = ChatGroq(
    model_name="llama-3.3-70b-versatile",
    groq_api_key=os.getenv("GROQ_API_KEY"),
    temperature=0
)

structured_llm1 = llm.with_structured_output(IntentSchema)

# ---------------------------
# Signal Classifier
# ---------------------------
def classify_signal(text: str):
    """
    Classify a PropTech news signal using LLM
    """
    prompt = f"""
            You are an AI system that identifies PROPTECH buying signals.

            STRICT RULES:

            1. Extract ONLY the actual COMPANY name mentioned in the news.
            2. Ignore events, conferences, awards, reports, and publications.
            3. If no company exists return company_name = "UNKNOWN".

            Examples of things to IGNORE:
            - Realty+ Conclave
            - PropTech Awards
            - Real Estate Summit
            - Conferences

            Examples of valid companies:
            - Spintly
            - Aurum PropTech
            - Zillow
            - Compass
            - OpenDoor

            Intent classification rules:

            YES → Strong buying signal
            - Startup funding
            - Product launch
            - Market expansion
            - Hiring surge
            - Strategic partnership
            - Acquisition

            MAYBE → Weak signal
            - Industry discussion
            - Trend reports
            - General announcements

            NO → Not relevant
            - Events
            - Awards
            - Editorial pieces
            - Articles without company

            IMPORTANT:
            - urgency MUST be an integer (not string)
            - Do NOT return urgency in quotes

            Urgency scoring:

            9-10 → Major funding or acquisition  
            7-8 → Growth signals or expansion  
            4-6 → Moderate signals  
            1-3 → Weak signals  

            Analyze this news signal:

            {text}
            """

    try:
        result = structured_llm1.invoke(prompt)

        # Extra safeguard to double check ai output
        if result.company_name.lower() in ["realty+", "conclave", "awards"]:
            result.intent = "NO"
            result.company_name = "UNKNOWN"

        result.urgency = int(result.urgency)

        return result

    except Exception as e:
        print(f"❌ Error classifying signal: {e}")
        return IntentSchema(
            intent="NO",
            company_name="UNKNOWN",
            signal_summary="Classification failed",
            reason="LLM error",
            urgency=0
        )
    
class outreachEmail(BaseModel):
    subject: str
    body: str

structured_llm2 = llm.with_structured_output(outreachEmail)

# email_writer
def generate_email(lead: dict):
    
    prompt = f"""
        You are a professional business development representative writing a thoughtful, personalized cold email.

        Your goal is to start a genuine conversation based on a real business signal.

        Context:
        - Company: {lead['Company Name']}
        - Contact Name: {lead['Contact Name']}
        - Role: {lead['Title']}
        - Recent News: {lead['Signal Summary']}
        - Signal Urgency: {lead['Intent Score']}/10

        ------------------------
        WRITING INSTRUCTIONS
        ------------------------

        1. Greeting:
        - Start with a proper greeting using first name
        Example: "Hi John,"

        2. Opening (IMPORTANT):
        - In the first 2–3 sentences, clearly reference the recent news
        - Show that you actually read it
        - Keep it natural, not exaggerated

        3. Body:
        - Add 1–2 short paragraphs explaining why you are reaching out
        - Connect your outreach to their recent activity
        - Briefly mention how you might help (keep it subtle, not salesy)

        4. Tone:
        - Human, conversational, professional
        - No buzzwords, no hype language
        - Avoid sounding like a template

        5. CTA:
        - Ask for a quick 15-minute chat
        - Keep it soft and optional

        6. Closing:
        - End with a proper closing:
        Examples:
        "Best regards,"
        "Thanks,"
        "Looking forward to hearing from you,"

        - Add a simple sender name:
        "Imran"

        ------------------------
        FORMAT (STRICT)
        ------------------------

        Subject: <natural, short subject line>

        Body:
        Hi <First Name>,

        <Opening paragraph referencing news>

        <Body paragraph explaining relevance>

        <Optional second body paragraph>

        <Soft CTA sentence>

        <Closing line>
        Imran

        ------------------------
        IMPORTANT RULES
        ------------------------

        - Minimum 120 words, maximum 180 words
        - Must include greeting AND closing
        - Must feel like a real human email
        - Do NOT write less than 100 words
        - Do NOT skip structure
        """

    result = structured_llm2.invoke(prompt)

    return {
        "subject": result.subject,
        "body": result.body
    }

def should_send_email(contact):
    email = contact.get("email", "")
    confidence = contact.get("confidence", 0)
    name = contact.get("name", "")

    if not email or not name:
        return False

    if confidence < 70:
        return False

    if len(name.split()) < 2:
        return False

    return True