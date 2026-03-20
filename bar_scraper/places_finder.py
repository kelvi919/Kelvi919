"""
Uses Google Places API to find bars, nightclubs, pubs, taverns, and dive bars
in Sarasota. Fetches details + reviews and attempts to identify the owner.
"""

import re
import time
import googlemaps
from config import GOOGLE_API_KEY, SEARCH_LOCATIONS, MAX_RESULTS_PER_QUERY, REQUEST_DELAY

# Type-based searches — Google's built-in categories
PLACE_TYPES = ["bar", "night_club"]

# Keyword searches to catch pubs, taverns, dive bars not tagged as bar/night_club
PLACE_KEYWORDS = ["pub", "tavern", "dive bar", "sports bar", "lounge"]

# Search radius in meters (~10 km covers all of Sarasota city proper)
SEARCH_RADIUS = 10000

# ── Owner name extraction from reviews ──────────────────────────────────────
#
# Two tiers:
#   HIGH-CONFIDENCE  — full "First Last" near an owner keyword  (weight 3)
#   MEDIUM-CONFIDENCE — first name only near a strong owner keyword (weight 1)
#
# We collect weighted votes across all reviews and pick the winner.
# A single first-name needs 3+ total weight (i.e. 3 separate mentions) to win
# over a zero-vote two-word name.

_NAME2 = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"   # two-word+ proper name
_NAME1 = r"([A-Z][a-z]{2,})"                     # single capitalized word ≥3 chars

# High-confidence patterns — group 1 must be the name
_HIGH_RE = [
    re.compile(rf"\bowner[,:\s]+{_NAME2}",                              re.IGNORECASE),
    re.compile(rf"\bowned\s+by\s+{_NAME2}",                             re.IGNORECASE),
    re.compile(rf"{_NAME2}[,\s]+(?:is\s+)?(?:the\s+)?owner\b",         re.IGNORECASE),
    re.compile(rf"{_NAME2}\s+\(owner\)",                                re.IGNORECASE),
    re.compile(rf"\bproprietor\s+{_NAME2}",                             re.IGNORECASE),
    re.compile(rf"{_NAME2}\s+(?:owns|founded|opened|started)\s+(?:this|the)\b", re.IGNORECASE),
    re.compile(rf"\bask\s+for\s+{_NAME2}[,\s]+(?:he|she|they).{{0,40}}own", re.IGNORECASE),
    re.compile(rf"\bmanaged\s+by\s+{_NAME2}",                           re.IGNORECASE),
    re.compile(rf"{_NAME2}[,\s]+(?:the\s+)?(?:owner|founder|proprietor)", re.IGNORECASE),
]

# Medium-confidence patterns — first name only
_MED_RE = [
    re.compile(rf"\bthe\s+owner[,\s]+{_NAME1}\b",                       re.IGNORECASE),
    re.compile(rf"\bowner\s+{_NAME1}\b",                                re.IGNORECASE),
    re.compile(rf"\b{_NAME1}\s+is\s+the\s+owner\b",                    re.IGNORECASE),
    re.compile(rf"\bowned\s+by\s+{_NAME1}\b",                          re.IGNORECASE),
    re.compile(rf"\bask\s+for\s+{_NAME1}[,\s]+(?:he|she).{{0,30}}own", re.IGNORECASE),
]

# Words that look like proper nouns but are NOT owner names
_REJECT = {
    "google", "yelp", "facebook", "instagram", "tripadvisor",
    "this", "the", "great", "good", "best", "happy", "nice",
    "staff", "bar", "pub", "place", "food", "service", "management",
    "definitely", "absolutely", "highly", "overall", "sarasota",
    "florida", "downtown", "manager", "owner",
}


def get_places_client():
    if not GOOGLE_API_KEY:
        raise ValueError(
            "GOOGLE_PLACES_API_KEY is missing.\n"
            "1. Go to https://console.cloud.google.com/\n"
            "2. Create a project and enable the 'Places API'\n"
            "3. Create an API key and paste it in your .env file"
        )
    return googlemaps.Client(key=GOOGLE_API_KEY)


def geocode_location(client, location):
    """Convert a city name string to (lat, lng) coordinates."""
    try:
        result = client.geocode(location)
        if result:
            loc = result[0]["geometry"]["location"]
            return (loc["lat"], loc["lng"])
    except Exception as e:
        print(f"  [!] Could not geocode '{location}': {e}")
    return None


def extract_owner_from_reviews(reviews):
    """
    Scan all Google reviews for owner name mentions using two tiers:
      - High-confidence (full name):  weight 3 each match
      - Medium-confidence (first name only): weight 1 each match

    A first-name-only result needs ≥3 total weight to be returned
    (i.e. it must appear 3 times, or a full name beats it at weight 3).
    """
    # scores keyed by lowercase name for dedup, values are (display_name, total_weight)
    scores: dict[str, list] = {}

    for review in reviews:
        text = review.get("text", "")
        if not text:
            continue

        # Find ALL matches in this review (findall, not just search)
        for pat in _HIGH_RE:
            for m in pat.finditer(text):
                name = m.group(1).strip()
                key  = name.lower()
                if key not in _REJECT and len(key) > 2:
                    entry = scores.setdefault(key, [name, 0])
                    entry[1] += 3

        for pat in _MED_RE:
            for m in pat.finditer(text):
                name = m.group(1).strip()
                key  = name.lower()
                if key not in _REJECT and len(key) > 2:
                    entry = scores.setdefault(key, [name, 0])
                    entry[1] += 1

    if not scores:
        return ""

    # Pick highest-weighted candidate; enforce minimum weight of 3 for single words
    best_key = max(scores, key=lambda k: scores[k][1])
    display_name, weight = scores[best_key]

    # Single-word names need ≥3 weight (at least 3 medium hits or 1 high hit)
    if len(display_name.split()) == 1 and weight < 3:
        # Try to find a two-word name with any weight
        two_word = [(k, v) for k, v in scores.items() if len(v[0].split()) >= 2]
        if two_word:
            best_key = max(two_word, key=lambda kv: kv[1][1])[0]
            display_name = scores[best_key][0]
        else:
            return ""  # not confident enough

    return display_name


def fetch_place_details(client, place_id):
    """Fetch detailed info + reviews for a single place."""
    try:
        result = client.place(
            place_id,
            fields=[
                "name",
                "formatted_address",
                "formatted_phone_number",
                "website",
                "url",
                "business_status",
                "reviews",
            ],
        )
        return result.get("result", {})
    except Exception as e:
        print(f"  [!] Could not fetch details for place_id {place_id}: {e}")
        return {}


def _paginate_nearby(client, coords, radius, **kwargs):
    """Run a places_nearby search with automatic pagination up to MAX_RESULTS_PER_QUERY."""
    places = []
    try:
        response = client.places_nearby(location=coords, radius=radius, **kwargs)
        places.extend(response.get("results", []))

        while "next_page_token" in response and len(places) < MAX_RESULTS_PER_QUERY:
            time.sleep(2)  # Google requires a short delay before next_page_token is valid
            response = client.places_nearby(
                location=coords,
                radius=radius,
                page_token=response["next_page_token"],
                **kwargs,
            )
            places.extend(response.get("results", []))
    except Exception as e:
        print(f"  [!] Search error: {e}")
    return places


def find_all_bars():
    """
    Search all configured locations for bars, nightclubs, pubs, taverns, and dive bars.
    For each place, fetches details and Google reviews to attempt owner identification.
    Returns a deduplicated list of bar dicts.
    """
    client = get_places_client()
    seen_place_ids = set()
    all_bars = []

    for location in SEARCH_LOCATIONS:
        print(f"\n[*] Location: {location}")

        coords = geocode_location(client, location)
        if not coords:
            print(f"  [!] Skipping — could not geocode '{location}'")
            continue
        print(f"  Coordinates: {coords[0]:.4f}, {coords[1]:.4f}")

        # --- Type-based searches (bar, night_club) ---
        for place_type in PLACE_TYPES:
            print(f"  Searching by type: {place_type}")
            raw = _paginate_nearby(client, coords, SEARCH_RADIUS, type=place_type)
            _process_results(client, raw, seen_place_ids, all_bars, location)
            time.sleep(REQUEST_DELAY)

        # --- Keyword searches (pub, tavern, dive bar, etc.) ---
        for keyword in PLACE_KEYWORDS:
            print(f"  Searching by keyword: '{keyword}'")
            raw = _paginate_nearby(client, coords, SEARCH_RADIUS, keyword=keyword)
            # Only keep results that are actually bars/clubs, not random restaurants
            bar_raw = [
                p for p in raw
                if set(p.get("types", [])) & {"bar", "night_club", "liquor_store"}
            ]
            _process_results(client, bar_raw, seen_place_ids, all_bars, location)
            time.sleep(REQUEST_DELAY)

    print(f"\n[*] Total unique bars/nightclubs found: {len(all_bars)}")
    return all_bars


def _process_results(client, raw_results, seen_place_ids, all_bars, location):
    """Deduplicate, fetch details+reviews, extract owner, and append to all_bars."""
    for place in raw_results:
        place_id = place.get("place_id")
        if not place_id or place_id in seen_place_ids:
            continue
        if place.get("business_status") == "CLOSED_PERMANENTLY":
            continue

        seen_place_ids.add(place_id)

        details = fetch_place_details(client, place_id)
        time.sleep(REQUEST_DELAY)

        reviews = details.get("reviews", [])
        owner_from_reviews = extract_owner_from_reviews(reviews)

        bar = {
            "place_id":           place_id,
            "business_name":      details.get("name") or place.get("name", ""),
            "address":            details.get("formatted_address") or place.get("vicinity", ""),
            "phone":              details.get("formatted_phone_number", ""),
            "website":            details.get("website", ""),
            "google_maps_url":    details.get("url", ""),
            "owner_from_reviews": owner_from_reviews,
            "search_location":    location,
        }

        all_bars.append(bar)
        owner_tag = f" | owner≈{owner_from_reviews}" if owner_from_reviews else ""
        print(f"    + {bar['business_name']} | {bar['phone'] or 'no phone'}{owner_tag}")
