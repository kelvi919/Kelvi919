"""
Uses Google Places API to find 21+ bars and nightclubs in Sarasota.
Returns a list of place dicts with name, address, phone, website, and place_id.
"""

import time
import googlemaps
from config import GOOGLE_API_KEY, SEARCH_LOCATIONS, MAX_RESULTS_PER_QUERY, REQUEST_DELAY

PLACE_TYPES = ["bar", "night_club"]

# Search radius in meters (~10 km covers all of Sarasota city proper)
SEARCH_RADIUS = 10000

# If a place also carries any of these types, it allows minors — skip it
FAMILY_TYPES = {"restaurant", "cafe", "bakery", "meal_delivery", "meal_takeaway", "food"}


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


def is_21_plus(place):
    """
    Returns True only if the place is a 21+ bar or nightclub.
    Google has no explicit age-restriction field, so we use type tags:
    - Must be typed as bar or night_club
    - Must NOT also be tagged as restaurant/cafe/food (those let minors in)
    """
    types = set(place.get("types", []))
    if not types & {"bar", "night_club"}:
        return False
    if types & FAMILY_TYPES:
        return False
    return True


def fetch_place_details(client, place_id):
    """Fetch detailed info for a single place (phone, website, etc.)."""
    try:
        result = client.place(
            place_id,
            fields=["name", "formatted_address", "formatted_phone_number", "website", "url", "business_status"],
        )
        return result.get("result", {})
    except Exception as e:
        print(f"  [!] Could not fetch details for place_id {place_id}: {e}")
        return {}


def search_nearby_by_type(client, coords, place_type, location_name):
    """
    Nearby Search for a specific type within SEARCH_RADIUS of coordinates.
    This is the correct API for geographic area searches — not text search.
    """
    places = []
    print(f"  Searching: {place_type} near {location_name}")

    try:
        response = client.places_nearby(location=coords, radius=SEARCH_RADIUS, type=place_type)
        places.extend(response.get("results", []))

        while "next_page_token" in response and len(places) < MAX_RESULTS_PER_QUERY:
            time.sleep(2)  # required delay before next_page_token is valid
            response = client.places_nearby(
                location=coords,
                radius=SEARCH_RADIUS,
                type=place_type,
                page_token=response["next_page_token"],
            )
            places.extend(response.get("results", []))

    except Exception as e:
        print(f"  [!] Search failed for {place_type} near {location_name}: {e}")

    return places


def find_all_bars():
    """
    Search all configured locations for 21+ bars and nightclubs.
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

        for place_type in PLACE_TYPES:
            raw_results = search_nearby_by_type(client, coords, place_type, location)
            time.sleep(REQUEST_DELAY)

            for place in raw_results:
                place_id = place.get("place_id")
                if not place_id or place_id in seen_place_ids:
                    continue

                if place.get("business_status") == "CLOSED_PERMANENTLY":
                    continue

                # Skip places that allow minors (restaurants/cafes that happen to have a bar)
                if not is_21_plus(place):
                    print(f"    - Skipped (not 21+): {place.get('name', '')} {place.get('types', [])}")
                    continue

                seen_place_ids.add(place_id)

                details = fetch_place_details(client, place_id)
                time.sleep(REQUEST_DELAY)

                bar = {
                    "place_id": place_id,
                    "business_name": details.get("name") or place.get("name", ""),
                    "address": details.get("formatted_address") or place.get("vicinity", ""),
                    "phone": details.get("formatted_phone_number", ""),
                    "website": details.get("website", ""),
                    "google_maps_url": details.get("url", ""),
                    "search_location": location,
                }

                all_bars.append(bar)
                print(f"    + {bar['business_name']} | {bar['phone'] or 'no phone'}")

    print(f"\n[*] Total unique 21+ bars/nightclubs found: {len(all_bars)}")
    return all_bars
