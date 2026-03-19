"""
Scrapes a bar's website to extract:
  - Owner / manager name
  - Email address(es)
  - Instagram handle
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Regex patterns
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
INSTAGRAM_RE = re.compile(
    r"(?:instagram\.com/|@)([a-zA-Z0-9_.]{1,30})"
)

# Keywords that suggest a page has owner info
OWNER_PAGE_KEYWORDS = ["about", "contact", "our-story", "story", "team", "staff", "meet", "owner"]

# Keywords near a name that suggest it's an owner/manager
OWNER_TITLE_KEYWORDS = [
    "owner", "co-owner", "founder", "co-founder", "proprietor",
    "operator", "manager", "general manager", "gm", "partner",
]


def _get_soup(url, timeout=10):
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"    [!] Failed to fetch {url}: {e}")
            return None


def _extract_emails(text):
    """Return list of unique emails found in text, filtering out image/file extensions."""
    emails = EMAIL_RE.findall(text)
    filtered = []
    skip_ext = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
    for e in emails:
        e_lower = e.lower()
        if not any(e_lower.endswith(ext) for ext in skip_ext):
            filtered.append(e.lower())
    return list(dict.fromkeys(filtered))  # dedupe preserving order


def _extract_instagram(text):
    """Return first Instagram handle found in text."""
    matches = INSTAGRAM_RE.findall(text)
    # Filter out generic/false positives
    bad = {"instagram", "share", "sharer", "p", "reel", "stories", "explore"}
    for match in matches:
        if match.lower() not in bad and len(match) > 1:
            return "@" + match
    return ""


def _find_owner_name(soup):
    """
    Try to extract an owner/manager name from the page.
    Looks for owner title keywords near proper nouns.
    """
    # Search in text nodes for patterns like "John Smith, Owner" or "Owner: Jane Doe"
    text = soup.get_text(separator=" ", strip=True)

    # Pattern: "Name, Owner" or "Name - Owner"
    pattern1 = re.compile(
        r"([A-Z][a-z]+(?: [A-Z][a-z]+)+)[,\-–]\s*(?:" + "|".join(OWNER_TITLE_KEYWORDS) + r")",
        re.IGNORECASE,
    )
    # Pattern: "Owner: Name" or "Owner | Name"
    pattern2 = re.compile(
        r"(?:" + "|".join(OWNER_TITLE_KEYWORDS) + r")[:\|]\s*([A-Z][a-z]+(?: [A-Z][a-z]+)+)",
        re.IGNORECASE,
    )
    # Pattern: "Owner Name" in heading tags
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "span", "div"]):
        tag_text = tag.get_text(separator=" ", strip=True)
        m = pattern1.search(tag_text)
        if m:
            return m.group(1).strip()
        m = pattern2.search(tag_text)
        if m:
            return m.group(1).strip()

    # Fallback: search full page text
    m = pattern1.search(text)
    if m:
        return m.group(1).strip()
    m = pattern2.search(text)
    if m:
        return m.group(1).strip()

    return ""


def _get_internal_links(soup, base_url):
    """Return internal links that likely lead to About/Contact pages."""
    base_domain = urlparse(base_url).netloc
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        # Must be same domain and match owner-page keywords
        if parsed.netloc == base_domain:
            path_lower = parsed.path.lower()
            if any(kw in path_lower for kw in OWNER_PAGE_KEYWORDS):
                links.append(full_url)
    return list(dict.fromkeys(links))  # dedupe


def scrape_website(website_url):
    """
    Scrape a bar website and return a dict with:
      owner_name, emails (comma-separated), instagram
    """
    result = {"owner_name": "", "email": "", "instagram": ""}

    if not website_url:
        return result

    # Normalize URL
    if not website_url.startswith("http"):
        website_url = "https://" + website_url

    # --- Scrape homepage ---
    soup = _get_soup(website_url)
    if not soup:
        return result

    page_text = soup.get_text(separator=" ", strip=True)
    page_html = str(soup)

    emails = _extract_emails(page_text)
    instagram = _extract_instagram(page_html)
    owner_name = _find_owner_name(soup)

    # --- Follow About/Contact sub-pages ---
    sub_links = _get_internal_links(soup, website_url)
    for link in sub_links[:4]:  # limit to 4 sub-pages
        time.sleep(0.8)
        sub_soup = _get_soup(link)
        if not sub_soup:
            continue
        sub_text = sub_soup.get_text(separator=" ", strip=True)
        sub_html = str(sub_soup)

        emails += _extract_emails(sub_text)
        if not instagram:
            instagram = _extract_instagram(sub_html)
        if not owner_name:
            owner_name = _find_owner_name(sub_soup)

    # Dedupe emails and join
    unique_emails = list(dict.fromkeys(emails))
    result["owner_name"] = owner_name
    result["email"] = ", ".join(unique_emails[:3])  # max 3 emails
    result["instagram"] = instagram

    return result
