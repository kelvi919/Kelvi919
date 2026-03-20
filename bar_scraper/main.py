"""
Bar Owner Scraper — Sarasota, FL
=================================
Finds bars, nightclubs, pubs, taverns, and every variety of bar via Google
Places API, then:
  - Scrapes each website for owner name, email, and social media
  - Falls back to DuckDuckGo if social links aren't on the website
  - Uses Claude AI to read Google reviews for owner name + 21+ detection

Usage:
    python main.py

Output:
    output/bar_owners_sarasota.csv
"""

import os
import time
import pandas as pd

from config import OUTPUT_FILE, REQUEST_DELAY
from places_finder import find_all_bars
from website_scraper import scrape_website, search_social_ddg


def run():
    print("=" * 60)
    print("  BAR OWNER SCRAPER — Sarasota, FL")
    print("=" * 60)

    # Step 1: Find all bars via Google Places (Claude reads reviews for owner + 21+)
    print("\n[STEP 1] Fetching bars from Google Places API...")
    bars = find_all_bars()

    if not bars:
        print("\n[!] No bars found. Check your API key and try again.")
        return

    # Step 2: Scrape each bar's website; fall back to DuckDuckGo for social links
    print(f"\n[STEP 2] Scraping websites + searching social media for {len(bars)} bars...")
    rows = []

    for i, bar in enumerate(bars, 1):
        name     = bar["business_name"]
        website  = bar.get("website", "")
        location = bar.get("search_location", "Sarasota FL")
        print(f"\n  [{i}/{len(bars)}] {name}")

        if website:
            print(f"    Website: {website}")
            web_data = scrape_website(website)
        else:
            print(f"    No website — skipping web scrape.")
            web_data = {"owner_name": "", "email": "", "instagram": "", "facebook": ""}

        # Social media fallback: DuckDuckGo if website didn't have links
        if not web_data["instagram"] or not web_data["facebook"]:
            print(f"    Searching social media via DuckDuckGo...")
            ddg_ig, ddg_fb = search_social_ddg(name, location)
            web_data["instagram"] = web_data["instagram"] or ddg_ig
            web_data["facebook"]  = web_data["facebook"]  or ddg_fb

        # Owner priority: website → Google reviews (Claude)
        owner_name   = web_data["owner_name"] or bar.get("owner_from_reviews", "")
        owner_source = ""
        if web_data["owner_name"]:
            owner_source = "website"
        elif bar.get("owner_from_reviews"):
            owner_source = "reviews (AI)"

        # 21+ from Claude's review analysis
        is_21_plus = bar.get("is_21_plus", False)

        row = {
            "Business Name": name,
            "Address":       bar.get("address", ""),
            "Phone":         bar.get("phone", ""),
            "Website":       website,
            "Google Maps":   bar.get("google_maps_url", ""),
            "21+ Only":      "Yes" if is_21_plus else "",
            "Owner Name":    owner_name,
            "Owner Source":  owner_source,
            "Email":         web_data["email"],
            "Instagram":     web_data["instagram"],
            "Facebook":      web_data["facebook"],
        }
        rows.append(row)

        print(f"    21+ Only:  {'Yes' if is_21_plus else 'No / Unknown'}")
        print(f"    Owner:     {owner_name or '—'}  [{owner_source or '—'}]")
        print(f"    Email:     {web_data['email'] or '—'}")
        print(f"    Instagram: {web_data['instagram'] or '—'}")
        print(f"    Facebook:  {web_data['facebook'] or '—'}")

        time.sleep(REQUEST_DELAY)

    # Step 3: Save to CSV
    print(f"\n[STEP 3] Saving results to {OUTPUT_FILE} ...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    df = pd.DataFrame(rows)
    df.drop_duplicates(subset=["Business Name", "Address"], inplace=True)
    df.sort_values("Business Name", inplace=True)
    df.to_csv(OUTPUT_FILE, index=False)

    total          = len(df)
    with_phone     = df["Phone"].astype(bool).sum()
    with_email     = df["Email"].astype(bool).sum()
    with_instagram = df["Instagram"].astype(bool).sum()
    with_facebook  = df["Facebook"].astype(bool).sum()
    with_owner     = df["Owner Name"].astype(bool).sum()
    from_website   = (df["Owner Source"] == "website").sum()
    from_reviews   = (df["Owner Source"] == "reviews (AI)").sum()
    is_21_count    = (df["21+ Only"] == "Yes").sum()

    print("\n" + "=" * 60)
    print(f"  DONE! {total} bars saved to {OUTPUT_FILE}")
    print(f"  With phone:          {with_phone}/{total}")
    print(f"  With email:          {with_email}/{total}")
    print(f"  With Instagram:      {with_instagram}/{total}")
    print(f"  With Facebook:       {with_facebook}/{total}")
    print(f"  With owner name:     {with_owner}/{total}")
    print(f"    └ from website:    {from_website}")
    print(f"    └ from reviews:    {from_reviews}")
    print(f"  21+ Only venues:     {is_21_count}/{total}")
    print("=" * 60)


if __name__ == "__main__":
    run()
