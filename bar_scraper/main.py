"""
Bar Owner Scraper — Sarasota, FL
=================================
Finds bars, nightclubs, pubs, taverns, and dive bars via Google Places API,
then scrapes each website for owner name, email, and Instagram handle.
Also scans Google reviews to identify the owner by name.

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
from website_scraper import scrape_website


def run():
    print("=" * 60)
    print("  BAR OWNER SCRAPER — Sarasota, FL")
    print("=" * 60)

    # Step 1: Find all bars via Google Places (includes review owner scan)
    print("\n[STEP 1] Fetching bars from Google Places API...")
    bars = find_all_bars()

    if not bars:
        print("\n[!] No bars found. Check your API key and try again.")
        return

    # Step 2: Scrape each bar's website for owner, email, Instagram
    print(f"\n[STEP 2] Scraping websites for {len(bars)} bars...")
    rows = []

    for i, bar in enumerate(bars, 1):
        name    = bar["business_name"]
        website = bar.get("website", "")
        print(f"\n  [{i}/{len(bars)}] {name}")

        if website:
            print(f"    Website: {website}")
            web_data = scrape_website(website)
        else:
            print(f"    No website found, skipping web scrape.")
            web_data = {"owner_name": "", "email": "", "instagram": ""}

        # Owner priority: website → Google reviews
        owner_name   = web_data["owner_name"] or bar.get("owner_from_reviews", "")
        owner_source = ""
        if web_data["owner_name"]:
            owner_source = "website"
        elif bar.get("owner_from_reviews"):
            owner_source = "reviews"

        row = {
            "Business Name": name,
            "Address":       bar.get("address", ""),
            "Phone":         bar.get("phone", ""),
            "Website":       website,
            "Google Maps":   bar.get("google_maps_url", ""),
            "Owner Name":    owner_name,
            "Owner Source":  owner_source,
            "Email":         web_data["email"],
            "Instagram":     web_data["instagram"],
        }
        rows.append(row)

        print(f"    Owner:     {owner_name or '—'}  [{owner_source or '—'}]")
        print(f"    Email:     {web_data['email'] or '—'}")
        print(f"    Instagram: {web_data['instagram'] or '—'}")

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
    with_owner     = df["Owner Name"].astype(bool).sum()
    from_website   = (df["Owner Source"] == "website").sum()
    from_reviews   = (df["Owner Source"] == "reviews").sum()

    print("\n" + "=" * 60)
    print(f"  DONE! {total} bars saved to {OUTPUT_FILE}")
    print(f"  With phone:          {with_phone}/{total}")
    print(f"  With email:          {with_email}/{total}")
    print(f"  With Instagram:      {with_instagram}/{total}")
    print(f"  With owner name:     {with_owner}/{total}")
    print(f"    └ from website:    {from_website}")
    print(f"    └ from reviews:    {from_reviews}")
    print("=" * 60)


if __name__ == "__main__":
    run()
