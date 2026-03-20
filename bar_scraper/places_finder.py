"""
Uses Google Places API to find bars, nightclubs, pubs, taverns, and dive bars
in Sarasota. Uses Claude AI to read Google reviews and identify the owner.
"""

import time
import anthropic
import googlemaps
from config import GOOGLE_API_KEY, ANTHROPIC_API_KEY, SEARCH_LOCATIONS, MAX_RESULTS_PER_QUERY, REQUEST_DELAY

PLACE_TYPES   = ["bar", "night_club"]
PLACE_KEYWORDS = ["pub", "tavern", "dive bar", "sports bar", "lounge"]
SEARCH_RADIUS  = 10000  # meters — covers all of Sarasota city proper

# ── Bar filter ───────────────────────────────────────────────────────────────
# Google tags many restaurants / golf clubs as "bar" because they have one.
# We only want places where bar or night_club is a primary type.

_EXCLUDE_VENUE = {"golf_course", "movie_theater", "bowling_alley", "stadium", "gym", "spa"}

# Name words that prove it's a real bar even if "restaurant" is also in types
_BAR_NAME_WORDS = {
    "bar", "pub", "tavern", "lounge", "cantina", "saloon",
    "ale", "taproom", "brewery", "brewhouse", "nightclub", "tiki",
}


def _is_real_bar(place):
    """
    True if this Google Place is primarily a bar / nightclub.
    Rejects golf clubs, steakhouses, bowling alleys, etc. that happen to
    be tagged 'bar' because they have a bar on the premises.
    """
    types    = place.get("types", [])
    type_set = set(types)
    name     = place.get("name", "").lower()

    if type_set & _EXCLUDE_VENUE:
        return False
    if not type_set & {"bar", "night_club"}:
        return False
    # bar/night_club is one of the first two types → primary venue
    if set(types[:2]) & {"bar", "night_club"}:
        return True
    # bar is deeper in the list but the name clearly says it's a bar
    if any(word in name for word in _BAR_NAME_WORDS):
        return True
    return False


# ── Claude-powered owner extraction ─────────────────────────────────────────

def _ask_claude_for_owner(bar_name, reviews):
    """
    Send the bar's Google reviews to Claude and ask it to identify the owner.
    Claude understands context — much more accurate than regex patterns.
    Returns the owner's name as a string, or empty string if not found.
    """
    if not ANTHROPIC_API_KEY:
        return ""
    if not reviews:
        return ""

    # Build a clean block of review text
    review_block = "\n\n".join(
        f'Review {i+1}: "{r.get("text", "").strip()}"'
        for i, r in enumerate(reviews)
        if r.get("text", "").strip()
    )
    if not review_block:
        return ""

    prompt = f"""You are analyzing customer reviews for a bar/nightclub called "{bar_name}".

Read these reviews carefully and determine if any customer mentions the owner by name.
Customers often write things like "the owner Mike was amazing", "owned by John Smith",
"Maria runs this place", "ask for Carlos, he's the owner", etc.

Reviews:
{review_block}

If you can identify the owner's name from the reviews, respond with ONLY the name (e.g. "John Smith" or "Maria").
If you cannot find a clear owner name, respond with exactly: UNKNOWN
Do not explain. Do not add any other text. Just the name or UNKNOWN."""

    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        result = response.content[0].text.strip()
        if result.upper() == "UNKNOWN" or not result:
            return ""
        return result
    except Exception as e:
        print(f"    [!] Claude API error: {e}")
        return ""


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
    Search Sarasota for bars, nightclubs, pubs, taverns, and dive bars.
    For each place, fetches details and Google reviews, then asks Claude
    to identify the owner from what customers wrote.
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
            print(f"    - Skipped: {place.get('name', '')} {place.get('types', [])[:3]}")
            continue

        seen_place_ids.add(place_id)

        details = fetch_place_details(client, place_id)
        time.sleep(REQUEST_DELAY)

        reviews            = details.get("reviews", [])
        bar_name           = details.get("name") or place.get("name", "")
        owner_from_reviews = _ask_claude_for_owner(bar_name, reviews)

        bar = {
            "place_id":            place_id,
            "business_name":       bar_name,
            "address":             details.get("formatted_address") or place.get("vicinity", ""),
            "phone":               details.get("formatted_phone_number", ""),
            "website":             details.get("website", ""),
            "google_maps_url":     details.get("url", ""),
            "owner_from_reviews":  owner_from_reviews,
            "search_location":     location,
        }

        all_bars.append(bar)
        owner_tag = f" | owner≈{owner_from_reviews}" if owner_from_reviews else ""
        print(f"    + {bar_name} | {bar['phone'] or 'no phone'}{owner_tag}")
