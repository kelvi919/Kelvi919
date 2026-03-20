"""
Scrapes a bar's website to extract:
  - Owner / manager name
  - Email address(es)
  - Instagram handle
  - Facebook page

Falls back to a DuckDuckGo search for social media when the website
doesn't contain direct links.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from duckduckgo_search import DDGS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Keywords that suggest a page has owner info
OWNER_PAGE_KEYWORDS = ["about", "contact", "our-story", "story", "team", "staff", "meet", "owner"]

# Title keywords near a name that suggest it's an owner/manager
OWNER_TITLE_KEYWORDS = [
    "owner", "co-owner", "founder", "co-founder", "proprietor",
    "operator", "manager", "general manager", "gm", "partner",
]

# Slugs to skip when extracting social media handles from URLs
_IG_SKIP  = {"p", "reel", "reels", "stories", "explore", "accounts", "share", "sharer", "tv", ""}
_FB_SKIP  = {"sharer", "share", "login", "dialog", "groups", "pages", "events", "profile.php", ""}


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
    skip_ext = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
    emails = []
    for e in EMAIL_RE.findall(text):
        e_lower = e.lower()
        if not any(e_lower.endswith(ext) for ext in skip_ext):
            emails.append(e_lower)
    return list(dict.fromkeys(emails))


def _extract_social(soup):
    """
    Extract Instagram and Facebook handles by scanning <a href> tags only.
    This avoids CSS/JS false positives (@media, @keyframes, @formatjs, etc.)
    that appear when running regex on raw HTML source.
    """
    instagram = ""
    facebook  = ""

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if not instagram and "instagram.com" in href:
            m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)/?", href)
            if m and m.group(1).lower() not in _IG_SKIP:
                instagram = "@" + m.group(1)

        if not facebook and "facebook.com" in href:
            # strip query strings before extracting slug
            clean = href.split("?")[0].rstrip("/")
            m = re.search(r"facebook\.com/([A-Za-z0-9_.]+)$", clean)
            if m and m.group(1).lower() not in _FB_SKIP:
                facebook = "fb.com/" + m.group(1)

        if instagram and facebook:
            break

    return instagram, facebook


def _find_owner_name(soup):
    """
    Try to extract an owner/manager name from the page.
    Checks heading + paragraph tags for owner-keyword patterns.
    """
    _title_group = "(?:" + "|".join(OWNER_TITLE_KEYWORDS) + ")"

    # Two-word+ name patterns (high confidence)
    two_word_name = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
    patterns = [
        re.compile(rf"{two_word_name}[,\-–]\s*{_title_group}", re.IGNORECASE),
        re.compile(rf"{_title_group}[:\|]\s*{two_word_name}", re.IGNORECASE),
        re.compile(rf"\bowned\s+by\s+{two_word_name}", re.IGNORECASE),
        re.compile(rf"\b{two_word_name}\s+(?:is\s+the|,\s*the)\s+{_title_group}", re.IGNORECASE),
        re.compile(rf"\b{two_word_name}\s+\({_title_group}\)", re.IGNORECASE),
        re.compile(rf"\b{two_word_name}\s+(?:owns|opened|founded|started)\s+(?:this|the)\b", re.IGNORECASE),
    ]

    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "span"]):
        text = tag.get_text(separator=" ", strip=True)
        for pat in patterns:
            m = pat.search(text)
            if m:
                return m.group(1).strip()

    # Fallback: scan full page text
    full_text = soup.get_text(separator=" ", strip=True)
    for pat in patterns:
        m = pat.search(full_text)
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
        if parsed.netloc == base_domain:
            path_lower = parsed.path.lower()
            if any(kw in path_lower for kw in OWNER_PAGE_KEYWORDS):
                links.append(full_url)
    return list(dict.fromkeys(links))


def search_social_ddg(bar_name, location="Sarasota FL"):
    """
    Search DuckDuckGo for a bar's Instagram and Facebook pages.
    Called when the website scrape didn't find social links.

    Tries three strategies per platform:
      1. "[bar name] [city] instagram"  — general search
      2. "[bar name] site:instagram.com" — pinned to the platform
      3. "[bar name] site:facebook.com"  — same for Facebook
    """
    instagram = ""
    facebook  = ""

    try:
        with DDGS() as ddgs:
            # ── Instagram ──────────────────────────────────────────────────
            for query in [
                f'"{bar_name}" {location} instagram',
                f'"{bar_name}" site:instagram.com',
            ]:
                if instagram:
                    break
                for r in ddgs.text(query, max_results=5):
                    url = r.get("href", "") or r.get("url", "")
                    if "instagram.com/" in url:
                        m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)/?", url)
                        if m and m.group(1).lower() not in _IG_SKIP:
                            instagram = "@" + m.group(1)
                            break
                time.sleep(0.6)

            # ── Facebook ───────────────────────────────────────────────────
            for query in [
                f'"{bar_name}" {location} facebook',
                f'"{bar_name}" site:facebook.com',
            ]:
                if facebook:
                    break
                for r in ddgs.text(query, max_results=5):
                    url = r.get("href", "") or r.get("url", "")
                    if "facebook.com/" in url:
                        clean = url.split("?")[0].rstrip("/")
                        m = re.search(r"facebook\.com/([A-Za-z0-9_.]+)$", clean)
                        if m and m.group(1).lower() not in _FB_SKIP:
                            facebook = "fb.com/" + m.group(1)
                            break
                time.sleep(0.6)

    except Exception as e:
        print(f"    [!] DDG search error for '{bar_name}': {e}")

    return instagram, facebook


def scrape_website(website_url):
    """
    Scrape a bar website and return a dict with:
      owner_name, email (comma-separated), instagram, facebook
    """
    result = {"owner_name": "", "email": "", "instagram": "", "facebook": ""}

    if not website_url:
        return result

    if not website_url.startswith("http"):
        website_url = "https://" + website_url

    soup = _get_soup(website_url)
    if not soup:
        return result

    emails     = _extract_emails(soup.get_text(separator=" ", strip=True))
    instagram, facebook = _extract_social(soup)
    owner_name = _find_owner_name(soup)

    # Follow About/Contact sub-pages for more info
    for link in _get_internal_links(soup, website_url)[:4]:
        time.sleep(0.8)
        sub = _get_soup(link)
        if not sub:
            continue
        emails += _extract_emails(sub.get_text(separator=" ", strip=True))
        if not instagram or not facebook:
            ig2, fb2 = _extract_social(sub)
            instagram = instagram or ig2
            facebook  = facebook  or fb2
        if not owner_name:
            owner_name = _find_owner_name(sub)

    result["owner_name"] = owner_name
    result["email"]      = ", ".join(list(dict.fromkeys(emails))[:3])
    result["instagram"]  = instagram
    result["facebook"]   = facebook

    return result
