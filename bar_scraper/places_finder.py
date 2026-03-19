"""
Uses Google Places API to find bars in Sarasota and nearby cities.
Returns a list of place dicts with name, address, phone, website, and place_id.
"""

import time
import googlemaps
from config import GOOGLE_API_KEY, SEARCH_LOCATIONS, BAR_SEARCH_TERMS, MAX_RESULTS_PER_QUERY, REQUEST_DELAY


def get_places_client():
    if not GOOGLE_API_KEY:
        raise ValueError(
            "GOOGLE_PLACES_API_KEY is missing.\n"
            "1. Go to https://console.cloud.google.com/\n"
            "2. Create a project and enable the 'Places API'\n"
            "3. Create an API key and paste it in your .env file"
        )
    return googlemaps.Client(key=GOOGLE_API_KEY)


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


def search_bars_in_location(client, location, search_term):
    """Search for bars matching search_term in a given location. Returns list of raw place results."""
    places = []
    query = f"{search_term} in {location}"
    print(f"  Searching: {query}")

    try:
        response = client.places(query=query)
        places.extend(response.get("results", []))

        # Google Places allows up to 3 pages (20 results each = 60 max)
        page = 1
        while "next_page_token" in response and len(places) < MAX_RESULTS_PER_QUERY:
            time.sleep(2)  # Google requires a short delay before next_page_token is valid
            response = client.places(query=query, page_token=response["next_page_token"])
            places.extend(response.get("results", []))
            page += 1

    except Exception as e:
        print(f"  [!] Search failed for '{query}': {e}")

    return places


def find_all_bars():
    """
    Search all configured locations and search terms.
    Returns a deduplicated list of bar dicts.
    """
    client = get_places_client()
    seen_place_ids = set()
    all_bars = []

    for location in SEARCH_LOCATIONS:
        print(f"\n[*] Location: {location}")
        for term in BAR_SEARCH_TERMS:
            raw_results = search_bars_in_location(client, location, term)
            time.sleep(REQUEST_DELAY)

            for place in raw_results:
                place_id = place.get("place_id")
                if not place_id or place_id in seen_place_ids:
                    continue

                # Skip permanently closed places
                if place.get("business_status") == "CLOSED_PERMANENTLY":
                    continue

                seen_place_ids.add(place_id)

                # Fetch full details (phone + website)
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
                print(f"    + Found: {bar['business_name']} | {bar['phone'] or 'no phone'}")

    print(f"\n[*] Total unique bars found: {len(all_bars)}")
    return all_bars
