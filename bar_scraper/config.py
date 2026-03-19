import os
from pathlib import Path

# Read .env file manually — works regardless of encoding or dotenv issues
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _val.strip())

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# Cities to search
SEARCH_LOCATIONS = [
    "Sarasota, FL",
]

# Output file
OUTPUT_FILE = "output/bar_owners_sarasota.csv"

# Request delay in seconds (be polite to servers)
REQUEST_DELAY = 1.5

# Max results per search query (Google max is 60 via pagination)
MAX_RESULTS_PER_QUERY = 60
