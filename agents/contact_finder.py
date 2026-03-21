from ddgs import DDGS
import re
import json
import os
import requests
from source.news_finder import extract_url

# Domains we never want as company website
BLOCKED_DOMAINS = [
    "linkedin.com",
    "wikipedia.org",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "crunchbase.com",
    "bloomberg.com",
    "glassdoor.com",
]

CACHE_FILE = r"data/cache_leads.json"


# ---------------------------
# Cache Helpers
# ---------------------------

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Cache load failed, starting fresh: {e}")
    return {}


def save_cache(cache: dict):
    try:
        os.makedirs("data", exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        print(f"⚠️ Cache save failed: {e}")


# ---------------------------
# Name Cleaner
# ---------------------------

def clean_name(title: str) -> str:
    """
    Split on ' - ' (with spaces) to preserve hyphenated names.
    'Mary-Jane Watson - CENTURY 21 | LinkedIn' -> 'Mary-Jane Watson'
    """
    parts = title.split(" - ")
    name = parts[0]
    name = name.replace("| LinkedIn", "").strip()
    name = re.sub(r"[^\w\s\-]", "", name)
    return name.strip()


# ---------------------------
# Website Finder
# ---------------------------

def find_company_website(company: str) -> str:
    """
    Find official company website using DuckDuckGo.
    Tries multiple queries, skips blocked domains.
    """
    queries = [
        f"{company} official website",
        f"{company} company site",
        f"{company}.com",
        f"{company} real estate company website"
    ]

    try:
        with DDGS() as ddgs:
            for query in queries:
                try:
                    results = list(ddgs.text(query, max_results=6))
                except Exception as e:
                    print(f"⚠️ DuckDuckGo query failed for '{query}': {e}")
                    continue

                for r in results:
                    url = r.get("href", "")
                    if not url:
                        continue
                    if not any(domain in url for domain in BLOCKED_DOMAINS):
                        return url

    except Exception as e:
        print(f"❌ Website search session failed: {e}")

    return ""


# ---------------------------
# LinkedIn Profile Search
# ---------------------------

def search_linkedin_profiles(company: str, role: str) -> list:
    """Search LinkedIn profiles using DuckDuckGo dorks."""
    query = f'site:linkedin.com/in "{company}" {role}'
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=8))
    except Exception as e:
        print(f"❌ LinkedIn search error for role '{role}': {e}")
        return []


def find_linkedin_contact(company: str) -> dict:
    """
    Find best leadership contact from LinkedIn.
    Priority: CEO → Founder → Co-Founder → CTO → President → MD
    """
    print(f"\n🔎 Searching leadership contact for: {company}")

    roles = [
        "CEO",
        "Founder",
        "Co-Founder",
        "CTO",
        "Chief Technology Officer",
        "President",
        "Managing Director"
    ]

    website = find_company_website(company)

    for role in roles:
        results = search_linkedin_profiles(company, role)

        for r in results:
            url = r.get("href", "")
            title = r.get("title", "")

            if not url or not title:
                continue

            if "linkedin.com/in/" not in url:
                continue

            name = clean_name(title)

            if len(name.split()) < 2:
                continue

            return {
                "name": name,
                "title": role,
                "linkedin": url,
                "website": website
            }

    print("⚠️ No leadership contact found")
    return {
        "name": "Not Found",
        "title": "",
        "linkedin": "",
        "website": website
    }


# ---------------------------
# Email Pattern Generator
# ---------------------------

def clean_name_part(part: str) -> str:
    """
    Strip all non-alpha characters from a name part.
    Handles cases like "Ashish." -> "ashish", "O'Brien" -> "obrien"
    """
    return re.sub(r"[^a-z]", "", part.lower())


def generate_email_patterns(name: str, domain: str) -> list:
    """
    Generate common email patterns from name + domain.
    Cleans first/last name before building patterns so punctuation
    from LinkedIn titles (e.g. "Ashish.") never bleeds into emails.
    Returns list ordered by most common → least common.
    """
    try:
        parts = name.lower().split()
        if len(parts) < 2:
            return []

        # Strip all non-alpha chars — removes periods, hyphens, apostrophes etc.
        first = clean_name_part(parts[0])
        last  = clean_name_part(parts[-1])

        if not first or not last:
            return []

        # Clean domain
        domain = domain.replace("https://", "").replace("http://", "")
        domain = domain.replace("www.", "").split("/")[0].strip()

        if not domain:
            return []

        return [
            f"{first}.{last}@{domain}",       # most common: john.smith@
            f"{first}{last}@{domain}",         # johnsmith@
            f"{first[0]}{last}@{domain}",      # jsmith@
            f"{first}@{domain}",               # john@
            f"{last}@{domain}",                # smith@
            f"{first[0]}.{last}@{domain}",     # j.smith@
        ]

    except Exception as e:
        print(f"⚠️ Pattern generation failed: {e}")
        return []


# ---------------------------
# Hunter Verifier
# ---------------------------

def verify_email_hunter(email: str) -> dict:
    """
    Verify a single email address using Hunter.io email-verifier API.
    Returns status and confidence score.
    """
    api_key = os.getenv("HUNTER_API_KEY")

    if not api_key:
        print("⚠️ HUNTER_API_KEY not set, skipping verification")
        return {"valid": False, "confidence": 0, "status": "no_api_key"}

    try:
        response = requests.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": api_key},
            timeout=6
        )

        if response.status_code != 200:
            print(f"⚠️ Hunter verifier returned {response.status_code}")
            return {"valid": False, "confidence": 0, "status": "api_error"}

        data = response.json().get("data", {})
        status = data.get("status", "")         # "valid", "invalid", "accept_all", "unknown"
        score = data.get("score", 0)            # confidence 0-100

        is_valid = status in ("valid", "accept_all") and score >= 50

        return {
            "valid": is_valid,
            "confidence": score,
            "status": status
        }

    except requests.Timeout:
        print("⚠️ Hunter verifier timed out")
        return {"valid": False, "confidence": 0, "status": "timeout"}
    except Exception as e:
        print(f"❌ Hunter verifier error: {e}")
        return {"valid": False, "confidence": 0, "status": "error"}


# ---------------------------
# Main Email Finder
# ---------------------------

def find_contact_email(name: str, domain: str) -> tuple:
    """
    Pattern-first email finder with Hunter verification.

    Flow:
    1. Generate all email patterns from name + domain
    2. Verify each pattern via Hunter email-verifier API
    3. Return first verified email with confidence score
    4. If none verified, return best-guess pattern with low confidence

    Returns: (email, confidence)
    """
    if not name or len(name.split()) < 2:
        print("⚠️ Invalid name for email generation")
        return "", 0

    # Clean domain
    clean_domain = extract_url(domain) if domain else ""
    if not clean_domain:
        print("⚠️ Could not extract domain from website")
        return "", 0

    patterns = generate_email_patterns(name, clean_domain)

    if not patterns:
        print("⚠️ No patterns generated")
        return "", 0

    print(f"📧 Verifying {len(patterns)} email patterns for {name} @ {clean_domain}")

    # Try each pattern via Hunter verifier
    for pattern in patterns:
        result = verify_email_hunter(pattern)

        if result["valid"]:
            print(f"✅ Verified email: {pattern} (confidence: {result['confidence']}%)")
            return pattern, result["confidence"]

        print(f"   ✗ {pattern} — {result['status']}")

    # No verified email found — return best-guess with low confidence
    best_guess = patterns[0]  # first.last@ is statistically most common
    print(f"⚠️ No verified email. Using best-guess: {best_guess}")
    return best_guess, 30