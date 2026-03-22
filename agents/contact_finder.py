from ddgs import DDGS
import re
import json
import os
import requests
from rapidfuzz import fuzz
from source.news_finder import extract_url

# ---------------------------
# Constants
# ---------------------------

CACHE_FILE = "data/cache_leads.json"

BLOCKED_DOMAINS = [
    "linkedin.com", "wikipedia.org", "facebook.com", "twitter.com",
    "instagram.com", "crunchbase.com", "bloomberg.com", "glassdoor.com",
    "indeed.com", "zoominfo.com", "pitchbook.com", "tracxn.com",
    "ambitionbox.com", "youtube.com", "reddit.com", "justdial.com",
    "sulekha.com", "quora.com", "medium.com",
]

NEWS_DOMAINS = [
    "techcrunch", "reuters", "forbes", "economictimes", "moneycontrol",
    "livemint", "businesswire", "prnewswire", "thehindu", "ndtv",
    "inc42", "yourstory", "venturebeat", "startupstory", "entrackr",
    "vccircle", "dealstreetasia", "businesstoday", "financialexpress",
]


# ---------------------------
# Cache
# ---------------------------

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Cache load failed: {e}")
    return {}


def save_cache(cache: dict):
    try:
        os.makedirs("data", exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        print(f"⚠️ Cache save failed: {e}")


# ---------------------------
# Name Cleaners
# ---------------------------

def clean_name(title: str) -> str:
    """
    Robustly extract just the person name from a LinkedIn result title.

    Handles all these real-world formats:
    - 'Ritesh Aggarwal -OYOfounder and groupCEOatOYO'  -> 'Ritesh Aggarwal'
    - 'Ashish Kumar - Aurum PropTech | LinkedIn'        -> 'Ashish Kumar'
    - 'Mary-Jane Watson - CENTURY 21 | LinkedIn'        -> 'Mary-Jane Watson'
    - 'Ritesh Agarwal - Founder & Group CEO at OYO'     -> 'Ritesh Agarwal'
    """
    # Strip | LinkedIn and everything after
    title = re.sub(r"\|.*", "", title).strip()

    # Split on spaced dash ( - ) OR a bare dash before uppercase (-OYO)
    # spaced dash is the normal LinkedIn separator
    # bare dash before uppercase catches camelCase junk like -OYOfounder
    parts = re.split(r"\s[\-–—]\s|(?<!\w)-(?=[A-Z])", title)
    name = parts[0].strip()

    # Drop anything in brackets - 'Name (CEO)' -> 'Name'
    name = re.sub(r"[\(\[].*", "", name).strip()

    # Keep only letters, spaces, hyphens
    name = re.sub(r"[^a-zA-Z\s\-]", "", name).strip()

    # Cap at 3 words — beyond that is usually role/company bleeding in
    words = name.split()
    if len(words) > 3:
        name = " ".join(words[:2])

    return name


def clean_name_part(part: str) -> str:
    """Strip all non-alpha chars: 'Ashish.' -> 'ashish'"""
    return re.sub(r"[^a-z]", "", part.lower())


# ---------------------------
# Website Finder
# ---------------------------

def _is_valid_website(url: str) -> bool:
    """
    Send a HEAD request to check if a URL is reachable.
    Returns True if status < 400.
    """
    try:
        resp = requests.head(
            url,
            timeout=5,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        return resp.status_code < 400
    except Exception:
        return False


def _guess_domain_from_name(company: str) -> list:
    """
    Build candidate domains from company name in priority order.
    Tries the most specific (full name) first, then shorter variants.

    Priority order matters — oyo.com must be tried before oyotownhouse.com
    would ever appear, and aurumproptech.in before aurum.com.
    """
    # Full name words — keep ALL words including "proptech", "tech" etc.
    # These are part of the brand domain (aurumproptech.in, officebanao.com)
    all_words = [w.lower() for w in company.split() if len(w) > 1]

    # Stripped words — remove legal suffixes only
    stripped = re.sub(
        r"\b(pvt|ltd|limited|private|inc|llc|the|and)\b",
        "", company, flags=re.IGNORECASE
    ).strip()
    stripped_words = [w.lower() for w in stripped.split() if len(w) > 1]

    seen = set()
    candidates = []

    def add(url):
        if url not in seen:
            seen.add(url)
            candidates.append(url)

    if stripped_words:
        w = stripped_words
        # Most specific first — full brand name
        add(f"https://{''.join(w)}.com")         # aurumproptech.com
        add(f"https://{''.join(w)}.in")           # aurumproptech.in  ← Indian companies
        add(f"https://{''.join(w)}.io")           # aurumproptech.io
        add(f"https://{'-'.join(w)}.com")         # aurum-proptech.com
        # Single primary word
        add(f"https://{w[0]}.com")                # aurum.com / oyo.com
        add(f"https://{w[0]}.in")                 # aurum.in / oyo.in
        # Two-word variant
        if len(w) >= 2:
            add(f"https://{''.join(w[:2])}.com")  # aurum + proptech
            add(f"https://{''.join(w[:2])}.in")

    return candidates


def find_company_website(company: str) -> str:
    """
    Find the official company website — 4-layer approach:

    Layer 0 — Try exact domain from company name directly via HEAD request.
              OYO -> oyo.com checked before any search. Fast and most accurate.
              Prevents short brand names (oyo, nuo, ola) matching wrong subdomains.

    Layer 1 — DDG search, but NOW requires ALL significant company words to appear
              in the domain (not just one). 'oyo' must fully match, not 'oyotownhouse'.
              Uses the TITLE of the search result (which Google/DDG show as company name)
              not just the URL.

    Layer 2 — Construct domain from company name + verify with HEAD request.
              e.g. 'Aurum PropTech' -> aurumproptech.com

    Layer 3 — Return best DDG result even without strict match (last resort).
    """
    print(f"🌐 Finding website for: {company}")

    # All significant words from company name (skip noise words)
    company_words = [
        w.lower() for w in re.sub(
            r"\b(pvt|ltd|limited|private|inc|llc|the|and|of)\b", "",
            company, flags=re.IGNORECASE
        ).split()
        if len(w) > 2
    ]

    # Short company name = single primary word (e.g. "OYO", "NoBroker")
    # For these, require EXACT word match in domain, not just substring
    # "oyo" must match "oyo.com" not "oyotownhouse.com"
    primary_word = company_words[0] if company_words else ""
    is_short_name = len(company_words) == 1

    def root_url(href: str) -> str:
        m = re.match(r"(https?://[^/]+)", href)
        return m.group(1) if m else href

    def is_clean(url: str) -> bool:
        u = url.lower()
        return (
            not any(d in u for d in BLOCKED_DOMAINS) and
            not any(n in u for n in NEWS_DOMAINS)
        )

    def domain_matches_company(domain: str) -> bool:
        """
        Check if a domain is actually the company's own domain.
        - Short single-word names (oyo): domain must be exactly word.com/word.in
          to avoid oyotownhouse.com, oyorooms.org etc.
        - Multi-word names (aurum proptech): ALL words must appear in domain
        """
        d = domain.lower().replace("https://", "").replace("www.", "").split("/")[0]
        # Remove TLD for comparison
        d_base = re.sub(r"\.(com|in|io|co|net|org|app)(\.[a-z]{2})?$", "", d)

        if is_short_name:
            # Exact match only: oyo.com -> d_base == "oyo"
            return d_base == primary_word
        else:
            # All significant words must appear in domain base
            return all(w in d_base for w in company_words)

    # --- Layer 0: Try direct domain via HEAD request (fastest, most accurate) ---
    direct_candidates = _guess_domain_from_name(company)
    for candidate in direct_candidates:
        if _is_valid_website(candidate):
            print(f"   ✅ Website (direct): {candidate}")
            return candidate

    # --- Fetch DDG results ---
    all_results = []
    try:
        with DDGS() as ddgs:
            for query in [
                f'"{company}" official website',
                f"{company} homepage",
            ]:
                try:
                    batch = list(ddgs.text(query, max_results=8))
                    all_results.extend(batch)
                except Exception as e:
                    print(f"   ⚠️ DDG query failed: {e}")
    except Exception as e:
        print(f"   ❌ DDG session failed: {e}")

    # --- Layer 1: DDG result where domain strictly matches company ---
    for r in all_results:
        href = r.get("href", "")
        if not href or not is_clean(href.lower()):
            continue
        if domain_matches_company(root_url(href)):
            result = root_url(href)
            print(f"   ✅ Website (DDG strict): {result}")
            return result

    # --- Layer 2: DDG result where title matches company name ---
    # The result title often IS the company name e.g. "OYO - Book Hotels & Homes"
    for r in all_results:
        href  = r.get("href", "")
        title = r.get("title", "").lower()
        if not href or not is_clean(href.lower()):
            continue
        # Title should start with or strongly contain the company name
        if all(w in title for w in company_words):
            result = root_url(href)
            print(f"   ✅ Website (DDG title match): {result}")
            return result

    # --- Layer 3: First clean DDG result ---
    for r in all_results:
        href = r.get("href", "")
        if href and is_clean(href.lower()):
            result = root_url(href)
            print(f"   ⚠️ Website (fallback DDG): {result}")
            return result

    print(f"   ❌ No website found for {company}")
    return ""


# ---------------------------
# LinkedIn Contact Finder
# ---------------------------

def _score_linkedin_result(r: dict, company: str) -> int:
    """
    Score a LinkedIn search result 0-100.

    KEY FIX — old scoring used partial_ratio which meant "aurum proptech"
    matched "aurum analytica" because both share "aurum". 

    New scoring requires ALL significant words of the company name
    to appear in the snippet — not just one shared word.

    Scoring:
    - Exact full company name in snippet:       +60 (strongest)
    - ALL company words present in snippet:     +40
    - MOST company words present (>=75%):       +20
    - Fuzzy full-string match >= 85:            +15 (fallback)
    - Valid /in/ profile URL:                   +10
    - Clean 2-word name:                        +10
    - PENALTY if a different company name is
      clearly present in the snippet:           -30
    """
    title = r.get("title", "")
    body  = r.get("body", "")
    url   = r.get("href", "")
    text  = f"{title} {body}".lower()
    co    = company.lower()

    # Significant words — skip short noise words
    co_words = [
        w for w in re.sub(
            r"\b(pvt|ltd|limited|private|inc|llc|the|and|of|at)\b",
            "", co, flags=re.IGNORECASE
        ).split()
        if len(w) > 2
    ]

    score = 0

    # Exact full company name present
    if co in text:
        score += 60
    else:
        words_found = sum(1 for w in co_words if w in text)
        total_words = len(co_words)

        if total_words > 0:
            ratio_found = words_found / total_words
            if ratio_found == 1.0:
                score += 40   # all words present
            elif ratio_found >= 0.75:
                score += 20   # most words present
            else:
                # Fallback: full fuzzy ratio — but use ratio not partial_ratio
                # ratio() compares full strings so "aurum analytica" won't
                # score high against "aurum proptech"
                full_ratio = fuzz.ratio(co, text[:len(co) * 3])
                if full_ratio >= 85:
                    score += 15

    # Valid profile URL
    if "linkedin.com/in/" in url:
        score += 10

    # Clean 2-word name
    name = clean_name(title)
    if len(name.split()) >= 2:
        score += 10

    # PENALTY: if snippet clearly mentions a different company
    # Detect by checking if a word that is NOT in co_words appears
    # right next to "ceo", "founder" etc. — heuristic for wrong company
    snippet_lower = text
    for word in co_words:
        if word not in snippet_lower:
            score -= 10   # each missing company word is a red flag

    return max(0, score)


def _search_ddg_linkedin(query: str, max_results: int = 6) -> list:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        print(f"   ⚠️ DDG LinkedIn search failed: {e}")
        return []


def find_linkedin_contact(company: str) -> dict:
    """
    Find the best LinkedIn contact for a company using a scoring approach.

    Old approach: take first result that passes basic checks → wrong person.
    New approach: collect ALL results across multiple queries and roles,
                  score each one, return the highest scorer.

    This means we never blindly trust the first result — we compare all
    candidates and pick the one most likely to actually be from the company.
    """
    print(f"\n🔎 Finding LinkedIn contact for: {company}")

    website = find_company_website(company)

    roles = ["CEO", "Founder", "Co-Founder", "CTO", "Managing Director"]

    # Collect all candidates from all role queries
    all_candidates = []

    for role in roles:
        queries = [
            f'site:linkedin.com/in "{company}" "{role}"',
            f'site:linkedin.com/in "{company}" {role}',
        ]

        for query in queries:
            results = _search_ddg_linkedin(query, max_results=5)

            for r in results:
                url   = r.get("href", "")
                title = r.get("title", "")

                if not url or not title:
                    continue
                if "linkedin.com/in/" not in url:
                    continue

                name = clean_name(title)
                if len(name.split()) < 2:
                    continue

                score = _score_linkedin_result(r, company)

                all_candidates.append({
                    "name":     name,
                    "title":    role,
                    "linkedin": url,
                    "website":  website,
                    "_score":   score,
                    "_snippet": r.get("body", "")[:100]
                })

    if not all_candidates:
        print("   ❌ No LinkedIn candidates found")
        return {"name": "Not Found", "title": "", "linkedin": "", "website": website}

    # Sort by score descending — highest confidence first
    all_candidates.sort(key=lambda x: x["_score"], reverse=True)

    best = all_candidates[0]
    print(f"   ✅ Best match: {best['name']} ({best['title']}) — confidence score: {best['_score']}/100")

    if best["_score"] < 30:
        print(f"   ⚠️ Low confidence ({best['_score']}/100) — contact may be incorrect")

    # Remove internal scoring fields before returning
    return {
        "name":     best["name"],
        "title":    best["title"],
        "linkedin": best["linkedin"],
        "website":  best["website"],
    }


# ---------------------------
# Email Pattern Generator
# ---------------------------

def generate_email_patterns(name: str, domain: str) -> list:
    """
    Generate 6 common email patterns. Strips punctuation from name parts.
    """
    try:
        parts = name.lower().split()
        if len(parts) < 2:
            return []

        first = clean_name_part(parts[0])
        last  = clean_name_part(parts[-1])

        if not first or not last:
            return []

        domain = re.sub(r"https?://", "", domain)
        domain = domain.replace("www.", "").split("/")[0].strip()

        if not domain or "." not in domain:
            return []

        return [
            f"{first}.{last}@{domain}",    # john.smith@   most common
            f"{first}{last}@{domain}",     # johnsmith@
            f"{first[0]}{last}@{domain}",  # jsmith@
            f"{first}@{domain}",           # john@
            f"{first[0]}.{last}@{domain}", # j.smith@
            f"{last}@{domain}",            # smith@
        ]

    except Exception as e:
        print(f"⚠️ Pattern generation failed: {e}")
        return []


# ---------------------------
# Hunter Email Verifier
# ---------------------------

def verify_email_hunter(email: str) -> dict:
    api_key = os.getenv("HUNTER_API_KEY")
    if not api_key:
        return {"valid": False, "confidence": 0, "status": "no_api_key"}

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": api_key},
            timeout=7
        )
        if resp.status_code != 200:
            return {"valid": False, "confidence": 0, "status": f"http_{resp.status_code}"}

        data     = resp.json().get("data", {})
        status   = data.get("status", "unknown")
        score    = data.get("score", 0)
        is_valid = status in ("valid", "accept_all") and score >= 50

        return {"valid": is_valid, "confidence": score, "status": status}

    except requests.Timeout:
        return {"valid": False, "confidence": 0, "status": "timeout"}
    except Exception as e:
        print(f"❌ Hunter error: {e}")
        return {"valid": False, "confidence": 0, "status": "error"}


# ---------------------------
# Main Email Finder
# ---------------------------

def find_contact_email(name: str, domain: str) -> tuple:
    """
    Pattern-first email finder with Hunter verification.
    Returns (email, confidence).
    """
    if not name or len(name.split()) < 2:
        return "", 0

    clean_domain = extract_url(domain) if domain else ""
    if not clean_domain:
        return "", 0

    patterns = generate_email_patterns(name, clean_domain)
    if not patterns:
        return "", 0

    print(f"📧 Verifying {len(patterns)} patterns for {name} @ {clean_domain}")

    for pattern in patterns:
        result = verify_email_hunter(pattern)
        if result["valid"]:
            print(f"   ✅ Verified: {pattern} ({result['confidence']}%)")
            return pattern, result["confidence"]
        print(f"   ✗ {pattern} — {result['status']}")

    print(f"   ⚠️ Fallback to best-guess: {patterns[0]}")
    return patterns[0], 30