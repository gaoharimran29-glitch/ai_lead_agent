import feedparser
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from urllib.parse import urlparse
from datetime import datetime, timezone
import time
import json
import os

# ---------------------------
# Keywords
# ---------------------------

KEYWORDS = [
    "proptech",
    "real estate app",
    "property platform",
    "real estate startup",
    "property tech",
    "proptech funding",
    "real estate digital",
    "proptech launch",
    "property investment"
]

# ---------------------------
# RSS Sources
# ---------------------------

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=proptech",
    "https://www.propmodo.com/feed",
]

# ---------------------------
# Seen Signals Cache
# Tracks article links already processed so reruns never repeat them.
# On first run: processes everything in the feed (no age limit).
# On reruns: only picks up articles published in the last 48 hours
#            that haven't been seen before.
# ---------------------------

SEEN_FILE = "data/seen_signals.json"


def load_seen() -> set:
    """Load set of already-processed article links from disk."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_seen(seen: set):
    """Persist the seen links set to disk."""
    try:
        os.makedirs("data", exist_ok=True)
        with open(SEEN_FILE, "w") as f:
            json.dump(list(seen), f)
    except IOError as e:
        print(f"⚠️ Could not save seen signals: {e}")


def is_first_run() -> bool:
    """True if no seen signals file exists yet — this is the very first run."""
    return not os.path.exists(SEEN_FILE)


# ---------------------------
# Helpers
# ---------------------------

def check_keywords(text: str) -> bool:
    text = text.lower()
    return any(keyword in text for keyword in KEYWORDS)


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text()


def extract_url(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "")


def get_source(link: str) -> str:
    return urlparse(link).netloc


def get_article_age_hours(entry) -> float:
    """Return how many hours ago this article was published. Returns 0 if unknown."""
    if not hasattr(entry, "published_parsed") or not entry.published_parsed:
        return 0.0

    try:
        published = datetime.fromtimestamp(
            time.mktime(entry.published_parsed),
            tz=timezone.utc
        )
        now = datetime.now(timezone.utc)
        return (now - published).total_seconds() / 3600
    except Exception:
        return 0.0


# ---------------------------
# Core Fetcher
# ---------------------------

def fetch_rss(url: str, seen: set, first_run: bool) -> list:
    """
    Fetch and filter signals from a single RSS feed.

    First run:  parse ALL entries in the feed, no age restriction.
                This builds your initial seen-signals baseline.

    Reruns:     only pick up articles < 48 hours old that haven't
                been seen before. Guarantees no duplicates across runs.
    """

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"❌ RSS fetch failed for {url}: {e}")
        return []

    if not feed.entries:
        print(f"⚠️ No entries found in feed: {url}")
        return []

    signals = []

    for entry in feed.entries:

        link = getattr(entry, "link", "")
        if not link:
            continue

        # Skip anything already processed in a previous run
        if link in seen:
            continue

        age_hours = get_article_age_hours(entry)

        # On reruns: skip articles older than 48 hours
        # On first run: take everything (age_hours == 0 means unknown date → include)
        if not first_run and age_hours > 48:
            continue

        text = (entry.title + clean_html(entry.get("summary", ""))).lower()

        if check_keywords(text):
            signals.append({
                "Title":   entry.title,
                "Link":    link,
                "Source":  get_source(link),
                "Summary": clean_html(entry.get("summary", "")),
                "AgeHours": round(age_hours, 1)
            })

    return signals


# ---------------------------
# Deduplication
# ---------------------------

def remove_duplicates(signals: list) -> list:
    """
    Remove near-duplicate articles within the same batch using
    token_sort_ratio so word-order differences don't fool the check.
    """
    unique = []

    for signal in signals:
        duplicate = False

        for u in unique:
            similarity = fuzz.token_sort_ratio(
                signal["Title"].lower(),
                u["Title"].lower()
            )
            if similarity > 75:
                duplicate = True
                break

        if not duplicate:
            unique.append(signal)

    return unique


# ---------------------------
# Public Entry Point
# ---------------------------

def monitor_signals() -> list:
    """
    Main function called by the pipeline.

    Flow:
    1. Check if this is the first run (no seen-signals file).
    2. Fetch all RSS feeds — full history on first run, 48hr only on reruns.
    3. Deduplicate within the current batch.
    4. Mark all fetched links as seen so they're never reprocessed.
    5. Return the clean signal list.
    """

    seen = load_seen()
    first_run = is_first_run()

    if first_run:
        print("🚀 First run detected — parsing full feed history")
    else:
        print(f"🔄 Rerun detected — fetching only signals from last 48 hours")

    signals = []

    for url in RSS_FEEDS:
        fetched = fetch_rss(url, seen, first_run)
        print(f"   📡 {get_source(url)}: {len(fetched)} new signals")
        signals += fetched

    # Deduplicate within this batch
    signals = remove_duplicates(signals)

    # Mark all fetched links as seen before returning
    for signal in signals:
        seen.add(signal["Link"])

    save_seen(seen)

    print(f"✅ Total signals this run: {len(signals)}")
    return signals