import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# Sarasota + nearby cities to search
SEARCH_LOCATIONS = [
    "Sarasota, FL",
    "Bradenton, FL",
    "Venice, FL",
    "North Port, FL",
    "Osprey, FL",
    "Nokomis, FL",
    "Englewood, FL",
    "Palmetto, FL",
    "Siesta Key, FL",
    "Longboat Key, FL",
    "Lakewood Ranch, FL",
]

# Search terms to find bars
BAR_SEARCH_TERMS = [
    "bar",
    "tavern",
    "pub",
    "nightclub",
    "lounge",
    "sports bar",
]

# Output file
OUTPUT_FILE = "output/bar_owners_sarasota.csv"

# Request delay in seconds (be polite to servers)
REQUEST_DELAY = 1.5

# Max results per search query (Google max is 60 via pagination)
MAX_RESULTS_PER_QUERY = 60
