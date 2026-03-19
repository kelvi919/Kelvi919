"""
Uses Google Places API to find bars in Sarasota and nearby cities.
Returns a list of place dicts with name, address, phone, website, and place_id.
"""

import time
import googlemaps
from config import GOOGLE_API_KEY, SEARCH_LOCATIONS, MAX_RESULTS_PER_QUERY, REQUEST_DELAY

PLACE_TYPES = ["bar", "night_club"]

# Search radius in meters for each city (~8 km covers most small FL cities well)
SEARCH_RADIUS = 8000


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
    """Convert a city name to (lat, lng) coordinates."""
    try:
        result = client.geocode(location)
        if result:
            loc = result[0]["geometry"]["location"]
            return (loc["lat"], loc["lng"])
    except Exception as e:
        print(f"  [!] Could not geocode '{location}': {e}")
    return None


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
    Use Nearby Search to find all places of a given type within SEARCH_RADIUS of coords.
    This is the correct API for 'find all bars near a location' — text search is not.
    Google returns only the requested type, so restaurants never appear.
    """
    places = []
    print(f"  Searching: {place_type} near {location_name}")

    try:
        response = client.places_nearby(location=coords, radius=SEARCH_RADIUS, type=place_type)
        places.extend(response.get("results", []))

        while "next_page_token" in response and len(places) < MAX_RESULTS_PER_QUERY:
            time.sleep(2)  # Google requires a short delay before next_page_token is valid
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
    Search all configured locations for bars and nightclubs.
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

        for place_type in PLACE_TYPES:
            raw_results = search_nearby_by_type(client, coords, place_type, location)
            time.sleep(REQUEST_DELAY)

            for place in raw_results:
                place_id = place.get("place_id")
                if not place_id or place_id in seen_place_ids:
                    continue

                if place.get("business_status") == "CLOSED_PERMANENTLY":
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

    print(f"\n[*] Total unique bars/nightclubs found: {len(all_bars)}")
    return all_bars
