"""
Uses Google Places API to find bars, nightclubs, pubs, taverns, and every
variety of bar in Sarasota. Uses Claude AI to:
  1. Identify the owner from Google reviews
  2. Determine whether the venue is 21+ only
"""

import time
import anthropic
import googlemaps
from config import (
    GOOGLE_API_KEY, ANTHROPIC_API_KEY,
    SEARCH_LOCATIONS, MAX_RESULTS_PER_QUERY, REQUEST_DELAY,
)

# ── What to search for ───────────────────────────────────────────────────────

# Google's built-in place type tags
PLACE_TYPES = ["bar", "night_club"]

# Keyword searches that catch specialty bars Google under-tags
PLACE_KEYWORDS = [
    "pub",
    "tavern",
    "dive bar",
    "sports bar",
    "lounge",
    "cocktail bar",
    "wine bar",
    "brewery",
    "taproom",
    "tiki bar",
    "karaoke bar",
    "jazz bar",
    "rooftop bar",
    "whiskey bar",
    "craft beer bar",
    "piano bar",
    "speakeasy",
    "pool bar",
    "beach bar",
    "tiki lounge",
]

SEARCH_RADIUS = 10000  # meters — covers all of Sarasota city proper

# ── Bar filter ───────────────────────────────────────────────────────────────
# Google tags golf clubs, steakhouses, etc. as "bar" because they have one.
# We only want venues that are primarily bars.

_EXCLUDE_VENUE = {
    "golf_course", "movie_theater", "bowling_alley",
    "stadium", "gym", "spa", "lodging",
}

_BAR_NAME_WORDS = {
    "bar", "pub", "tavern", "lounge", "cantina", "saloon",
    "ale", "taproom", "brewery", "brewhouse", "nightclub", "tiki",
    "speakeasy", "drinkery",
}


def _is_real_bar(place):
    """
    True only if this Google Place is primarily a bar / nightclub.
    Rejects golf clubs, steakhouses, etc. that happen to have a bar tagged.

    Rules:
      - Hard-exclude obvious non-bar venues (golf course, gym, etc.)
      - bar/night_club must be in the first two types (Google's primary tags)
      - OR the place name contains a clear bar keyword
    """
    types    = place.get("types", [])
    type_set = set(types)
    name     = place.get("name", "").lower()

    if type_set & _EXCLUDE_VENUE:
        return False
    if not type_set & {"bar", "night_club"}:
        return False
    if set(types[:2]) & {"bar", "night_club"}:
        return True
    if any(word in name for word in _BAR_NAME_WORDS):
        return True
    return False


# ── Claude AI analysis ───────────────────────────────────────────────────────

def _ask_claude(bar_name, place_types, reviews):
    """
    Send the bar's place types and Google reviews to Claude.
    Claude determines:
      1. Who the owner is (from review mentions)
      2. Whether the venue is 21+ only

    Returns (owner_name: str, is_21_plus: bool)
    """
    if not ANTHROPIC_API_KEY or not reviews:
        return "", False

    review_block = "\n\n".join(
        f'Review {i+1}: "{r.get("text", "").strip()}"'
        for i, r in enumerate(reviews)
        if r.get("text", "").strip()
    )
    if not review_block:
        return "", False

    types_str = ", ".join(place_types) if place_types else "bar"

    prompt = f"""You are analyzing data for a bar/nightclub called "{bar_name}".

Google place types: {types_str}

Customer reviews:
{review_block}

Answer BOTH questions. Be concise.

1. OWNER: If any review clearly names the owner/founder/proprietor, write their name \
(first + last if mentioned). If no owner name appears, write UNKNOWN.

2. AGE_RESTRICTION: Is this venue 21+ only (adults-only, no minors allowed)?
   Write YES  — if there is clear evidence: reviews mention ID checks, "21 and over", \
"no one under 21", the place type is night_club, or customers mention being carded.
   Write NO   — if no such evidence exists.
   Write UNSURE — if there are vague hints but nothing definitive.

Respond in exactly this format (two lines, nothing else):
OWNER: [name or UNKNOWN]
AGE_RESTRICTION: [YES / NO / UNSURE]"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp   = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

        owner      = ""
        is_21_plus = False

        for line in text.splitlines():
            line = line.strip()
            if line.startswith("OWNER:"):
                val = line.split(":", 1)[1].strip()
                if val.upper() != "UNKNOWN" and val:
                    owner = val
            elif line.startswith("AGE_RESTRICTION:"):
                val = line.split(":", 1)[1].strip().upper()
                is_21_plus = (val == "YES")

        return owner, is_21_plus

    except Exception as e:
        print(f"    [!] Claude API error: {e}")
        return "", False


# ── Google Places helpers ────────────────────────────────────────────────────

def get_places_client():
    if not GOOGLE_API_KEY:
        raise ValueError(
            "GOOGLE_PLACES_API_KEY is missing.\n"
            "Add it to your .env file: GOOGLE_PLACES_API_KEY=your_key_here"
        )
    return googlemaps.Client(key=GOOGLE_API_KEY)


def geocode_location(client, location):
    try:
        result = client.geocode(location)
        if result:
            loc = result[0]["geometry"]["location"]
            return (loc["lat"], loc["lng"])
    except Exception as e:
        print(f"  [!] Could not geocode '{location}': {e}")
    return None


def fetch_place_details(client, place_id):
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
        print(f"  [!] Could not fetch details for {place_id}: {e}")
        return {}


def _paginate_nearby(client, coords, radius, **kwargs):
    places = []
    try:
        response = client.places_nearby(location=coords, radius=radius, **kwargs)
        places.extend(response.get("results", []))
        while "next_page_token" in response and len(places) < MAX_RESULTS_PER_QUERY:
            time.sleep(2)
            response = client.places_nearby(
                location=coords, radius=radius,
                page_token=response["next_page_token"], **kwargs,
            )
            places.extend(response.get("results", []))
    except Exception as e:
        print(f"  [!] Search error: {e}")
    return places


# ── Main entry point ─────────────────────────────────────────────────────────

def find_all_bars():
    """
    Search every configured location for all varieties of bar.
    For each result, fetches Google reviews and asks Claude to identify
    the owner and whether the venue is 21+ only.
    Returns a deduplicated list of bar dicts.
    """
    client         = get_places_client()
    seen_place_ids = set()
    all_bars       = []

    for location in SEARCH_LOCATIONS:
        print(f"\n[*] Location: {location}")
        coords = geocode_location(client, location)
        if not coords:
            print(f"  [!] Skipping — could not geocode '{location}'")
            continue
        print(f"  Coordinates: {coords[0]:.4f}, {coords[1]:.4f}")

        for place_type in PLACE_TYPES:
            print(f"  Searching by type: {place_type}")
            raw = _paginate_nearby(client, coords, SEARCH_RADIUS, type=place_type)
            _process_results(client, raw, seen_place_ids, all_bars, location)
            time.sleep(REQUEST_DELAY)

        for keyword in PLACE_KEYWORDS:
            print(f"  Searching by keyword: '{keyword}'")
            raw = _paginate_nearby(client, coords, SEARCH_RADIUS, keyword=keyword)
            _process_results(client, raw, seen_place_ids, all_bars, location)
            time.sleep(REQUEST_DELAY)

    print(f"\n[*] Total unique bars/nightclubs found: {len(all_bars)}")
    return all_bars


def _process_results(client, raw_results, seen_place_ids, all_bars, location):
    for place in raw_results:
        place_id = place.get("place_id")
        if not place_id or place_id in seen_place_ids:
            continue
        if place.get("business_status") == "CLOSED_PERMANENTLY":
            continue
        if not _is_real_bar(place):
            print(f"    - Skipped (not a bar): {place.get('name', '')} {place.get('types', [])[:3]}")
            continue

        seen_place_ids.add(place_id)

        details = fetch_place_details(client, place_id)
        time.sleep(REQUEST_DELAY)

        bar_name    = details.get("name") or place.get("name", "")
        place_types = place.get("types", [])
        reviews     = details.get("reviews", [])

        owner, is_21_plus = _ask_claude(bar_name, place_types, reviews)

        bar = {
            "place_id":            place_id,
            "business_name":       bar_name,
            "address":             details.get("formatted_address") or place.get("vicinity", ""),
            "phone":               details.get("formatted_phone_number", ""),
            "website":             details.get("website", ""),
            "google_maps_url":     details.get("url", ""),
            "owner_from_reviews":  owner,
            "is_21_plus":          is_21_plus,
            "search_location":     location,
        }

        all_bars.append(bar)

        flags = []
        if owner:
            flags.append(f"owner≈{owner}")
        if is_21_plus:
            flags.append("21+")
        tag = " | " + " | ".join(flags) if flags else ""
        print(f"    + {bar_name} | {bar['phone'] or 'no phone'}{tag}")
