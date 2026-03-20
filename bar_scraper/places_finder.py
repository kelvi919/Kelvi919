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

# Patterns to find owner names mentioned in reviews
# e.g. "the owner John", "owner Maria runs", "John Smith, the owner"
_OWNER_RE = [
    re.compile(r"\bowner[,\s]+([A-Z][a-z]+(?: [A-Z][a-z]+)+)", re.IGNORECASE),
    re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)[,\s]+(?:is\s+the\s+)?owner", re.IGNORECASE),
    re.compile(r"\bowned\s+by\s+([A-Z][a-z]+(?: [A-Z][a-z]+)+)", re.IGNORECASE),
    re.compile(r"\bask\s+for\s+([A-Z][a-z]+(?: [A-Z][a-z]+)+)[,\s]+(?:he|she|they)?.{0,30}own", re.IGNORECASE),
    re.compile(r"\bproprietor\s+([A-Z][a-z]+(?: [A-Z][a-z]+)+)", re.IGNORECASE),
    re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\s+(?:runs|operates|opened)\s+(?:this|the)\s+(?:bar|place|pub|club|spot)", re.IGNORECASE),
]

# False-positive owner names to reject
_REJECT_NAMES = {
    "Google", "Yelp", "Facebook", "Instagram", "Happy Hour",
    "The Bar", "This Place", "Great Service",
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
    Scan Google reviews for owner name mentions.
    Customers often write things like 'the owner John was amazing'
    or 'Maria, the owner, greeted us personally'.
    Returns the best candidate name, or empty string.
    """
    candidates = {}
    for review in reviews:
        text = review.get("text", "")
        if not text:
            continue
        for pattern in _OWNER_RE:
            m = pattern.search(text)
            if m:
                name = m.group(1).strip()
                if name not in _REJECT_NAMES and len(name.split()) >= 2:
                    candidates[name] = candidates.get(name, 0) + 1

    if not candidates:
        return ""
    # Return the name mentioned most often across reviews
    return max(candidates, key=candidates.get)


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
