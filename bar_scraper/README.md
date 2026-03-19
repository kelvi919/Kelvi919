# Bar Owner Scraper — Sarasota, FL

Finds bars in Sarasota and nearby cities, scrapes each business website
for the owner's name, email, and Instagram handle, and cross-references
Florida's **SunBiz** (Division of Corporations) database to verify the
business is active and find the registered owner/manager.
Results are saved to a CSV ready for outreach.

---

## Setup

### 1. Get a Google Places API Key (free tier included)

1. Go to https://console.cloud.google.com/
2. Create a new project (e.g. "Bar Scraper")
3. Go to **APIs & Services → Enable APIs**
4. Enable **Places API**
5. Go to **APIs & Services → Credentials → Create API Key**
6. Copy the key

### 2. Install dependencies

```bash
cd bar_scraper
pip install -r requirements.txt
```

### 3. Add your API key

```bash
cp .env.example .env
# Then open .env and paste your key:
# GOOGLE_PLACES_API_KEY=AIza...
```

### 4. Run it

```bash
python main.py
```

Results are saved to `output/bar_owners_sarasota.csv`

---

## What it collects

| Column | Source |
|---|---|
| Business Name | Google Places |
| Address | Google Places |
| Phone | Google Places |
| Website | Google Places |
| Owner Name | Website first, SunBiz as fallback |
| Owner Source | `website` or `sunbiz` — where the name came from |
| Owner Title (SunBiz) | e.g. MGR, PRES, MEMBER |
| SunBiz Active | Yes / No — is the LLC currently active? |
| SunBiz Entity | Exact registered entity name |
| SunBiz Address | Principal address on file with the state |
| SunBiz URL | Direct link to their SunBiz filing page |
| Email | Business website |
| Instagram | Business website |
| Google Maps URL | Google Places |
| Search City | Which city the bar was found in |

---

## Cities covered

- Sarasota
- Bradenton
- Venice
- North Port
- Osprey
- Nokomis
- Englewood
- Palmetto
- Siesta Key
- Longboat Key
- Lakewood Ranch

Add or remove cities in `config.py` → `SEARCH_LOCATIONS`.

---

## Notes

- Google Places API has a **free tier** ($200/month credit ≈ ~10,000 requests).
  A full run typically uses a few hundred requests, well within the free limit.
- Owner name detection works best on bars with an About or Contact page.
  Many small bars won't have websites — those rows will still appear with phone number.
- **SunBiz** is Florida's free public business registry — no API key needed.
  If the website doesn't list an owner, SunBiz often has the registered manager/member.
- Only **ACTIVE** SunBiz entities are used. Dissolved or inactive LLCs are ignored.
- The scraper is polite (1.5s delay between requests) to avoid being blocked.
