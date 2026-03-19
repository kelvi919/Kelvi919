"""
Searches Florida's SunBiz (Division of Corporations) database
to verify a business is ACTIVE and return its owner/manager name + address.

SunBiz is a public government database — free to query.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

SUNBIZ_SEARCH_URL = "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
SUNBIZ_BASE_URL   = "https://search.sunbiz.org"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Minimum name similarity (0–1) to accept a result as a match
MIN_SIMILARITY = 0.60

# Officer/manager title codes SunBiz uses — we want the actual owners, not just agents
OWNER_TITLES = {
    "MGR",     # Manager (LLC)
    "MGRM",    # Manager Member (LLC)
    "PRES",    # President (Corp)
    "CEO",     # CEO (Corp)
    "OWNER",   # Owner
    "PARTNER", # Partner
    "MEMBER",  # Member (LLC)
    "VP",      # Vice President
    "DIR",     # Director
    "TREAS",   # Treasurer
    "SECY",    # Secretary
}

# Registered agent title — lower priority but still useful as fallback
AGENT_TITLES = {"RAGT", "RA", "REGISTERED AGENT"}


def _similarity(a, b):
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _fetch(url, params=None, timeout=12):
    """GET a URL and return BeautifulSoup, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"    [SunBiz] Request failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 1: Search for matching entities
# ---------------------------------------------------------------------------

def _search_entities(business_name):
    """
    Query SunBiz for entities matching business_name.
    Returns list of dicts: {name, status, detail_url}
    """
    params = {
        "inquirytype":                  "EntityName",
        "inquiryDirectionType":         "ForwardList",
        "searchNameOrder":              "",
        "masterDataTopmainSearchStatus": "",
        "mainSearchStatus":             "",
        "searchTerm":                   business_name,
        "fileNumber":                   "",
        "searchOrder":                  "",
    }
    soup = _fetch(SUNBIZ_SEARCH_URL, params=params)
    if not soup:
        return []

    results = []

    # SunBiz renders results in a <table> — grab the first one with rows
    table = soup.find("table", {"id": "search-results"})
    if not table:
        table = soup.find("table")   # fallback: first table on page

    if not table:
        return []

    for row in table.find_all("tr")[1:]:   # skip header row
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        name_tag = cols[0].find("a")
        if not name_tag:
            continue

        name        = name_tag.get_text(strip=True)
        href        = name_tag.get("href", "")
        detail_url  = (SUNBIZ_BASE_URL + href) if href.startswith("/") else href
        status      = cols[2].get_text(strip=True).upper()

        results.append({
            "name":       name,
            "status":     status,
            "detail_url": detail_url,
        })

    return results


# ---------------------------------------------------------------------------
# Step 2: Scrape detail page for officers
# ---------------------------------------------------------------------------

def _parse_officers(soup):
    """
    Extract officer list from a SunBiz detail page.
    SunBiz detail pages use a pattern of label/info spans inside detailSection divs.

    Returns list of dicts: {name, title, address}
    """
    officers = []

    # Each officer block looks like:
    #   <div class="detailSection officer">
    #     <div> <span class="label">Title</span> <span class="label">Name</span> ... </div>
    #     <div> <span class="info">MGR</span>    <span class="info">JOHN DOE</span> ... </div>
    #   </div>

    officer_section = None
    for section in soup.find_all("div", class_=re.compile(r"officer", re.I)):
        officer_section = section
        break

    if not officer_section:
        # Fallback: find any detailSection that contains officer-like content
        for section in soup.find_all("div", class_=re.compile(r"detailSection", re.I)):
            text = section.get_text(" ", strip=True).upper()
            if any(t in text for t in ("MGR", "PRES", "RAGT", "MEMBER", "OWNER")):
                officer_section = section
                break

    if not officer_section:
        return officers

    # SunBiz layout: pairs of <div> rows — first has labels, rest have values
    # More robust: collect all <span class="info"> lines grouped by their parent <div>
    info_rows = []
    for div in officer_section.find_all("div", recursive=False):
        spans = div.find_all("span", class_=re.compile(r"info|detail", re.I))
        if spans:
            info_rows.append([s.get_text(strip=True) for s in spans])

    # Each info_row is typically: [TITLE, NAME, ADDRESS_LINE1, CITY_STATE_ZIP]
    for row in info_rows:
        if len(row) < 2:
            continue
        title   = row[0].upper().strip()
        name    = row[1].strip()
        address = ", ".join(row[2:]).strip() if len(row) > 2 else ""

        if name:
            officers.append({"name": name, "title": title, "address": address})

    return officers


def _get_detail(detail_url):
    """Fetch detail page and return (officers_list, principal_address)."""
    soup = _fetch(detail_url)
    if not soup:
        return [], ""

    officers = _parse_officers(soup)

    # Principal address is in the address section near the top
    principal_address = ""
    for section in soup.find_all("div", class_=re.compile(r"detailSection", re.I)):
        label = section.find("span", class_=re.compile(r"label", re.I))
        if label and "principal" in label.get_text(strip=True).lower():
            info_spans = section.find_all("span", class_=re.compile(r"info", re.I))
            principal_address = ", ".join(s.get_text(strip=True) for s in info_spans if s.get_text(strip=True))
            break

    return officers, principal_address


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_sunbiz(business_name):
    """
    Main function. Given a business name:
      1. Searches SunBiz
      2. Finds best matching ACTIVE entity (similarity >= MIN_SIMILARITY)
      3. Returns officer/manager info

    Returns dict:
    {
        "found":          bool,
        "active":         bool,
        "entity_name":    str,
        "owner_name":     str,   # best owner/manager candidate
        "owner_title":    str,
        "all_officers":   [{name, title, address}],
        "principal_address": str,
        "detail_url":     str,
    }
    """
    empty = {
        "found":             False,
        "active":            False,
        "entity_name":       "",
        "owner_name":        "",
        "owner_title":       "",
        "all_officers":      [],
        "principal_address": "",
        "detail_url":        "",
    }

    if not business_name or not business_name.strip():
        return empty

    # Strip common suffixes that SunBiz wouldn't include, to improve matching
    clean_name = re.sub(
        r"\b(bar|lounge|pub|tavern|grill|restaurant|night ?club|sports bar|& grill|the |'s)\b",
        " ", business_name, flags=re.I
    ).strip()
    clean_name = re.sub(r"\s+", " ", clean_name).strip() or business_name

    candidates = _search_entities(business_name)

    # Also try the cleaned name if it differs
    if clean_name.lower() != business_name.lower() and len(candidates) == 0:
        time.sleep(1)
        candidates += _search_entities(clean_name)

    if not candidates:
        return empty

    # Score each result: only consider ACTIVE entities above similarity threshold
    best = None
    best_score = 0.0

    for c in candidates:
        if c["status"] != "ACTIVE":
            continue
        score = max(
            _similarity(business_name, c["name"]),
            _similarity(clean_name, c["name"]),
        )
        if score > best_score and score >= MIN_SIMILARITY:
            best_score = score
            best = c

    if not best:
        # No active match above threshold — report what we found
        result = dict(empty)
        result["found"]  = True
        result["active"] = False
        return result

    # Fetch detail page
    time.sleep(1)
    officers, principal_address = _get_detail(best["detail_url"])

    # Pick best officer: prefer actual owner/manager titles over registered agent
    owner = None
    for officer in officers:
        t = officer["title"].upper()
        if any(ot in t for ot in OWNER_TITLES):
            owner = officer
            break
    # Fallback to registered agent if no owner title found
    if not owner and officers:
        owner = officers[0]

    return {
        "found":             True,
        "active":            True,
        "entity_name":       best["name"],
        "owner_name":        owner["name"]    if owner else "",
        "owner_title":       owner["title"]   if owner else "",
        "all_officers":      officers,
        "principal_address": principal_address,
        "detail_url":        best["detail_url"],
    }
