"""Check what data is available from the search/render endpoint."""
import json
import requests
import urllib.parse

APP_ID = "3678970"
ITEM = "Frozen Orb (Immortal) A"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

encoded = urllib.parse.quote_plus(ITEM)
url = f"https://steamcommunity.com/market/search/render/?query={encoded}&appid={APP_ID}&count=1&norender=1"
print("URL:", url)

r = requests.get(url, headers=HEADERS, timeout=15)
print("Status:", r.status_code)
data = r.json()

if data.get("results"):
    item = data["results"][0]
    print("\n=== Top-level keys ===")
    print(json.dumps(list(item.keys()), indent=2))

    print("\n=== asset_description keys ===")
    desc = item.get("asset_description", {})
    print(json.dumps(list(desc.keys()), indent=2))

    print("\n=== Important key values ===")
    for key in ["name_color", "type", "icon_url", "icon_url_large", "classid", "instanceid", "market_hash_name"]:
        print(f"  {key}: {desc.get(key)}")

    print("\n=== sell_listings data ===")
    for key in ["sell_listings", "sell_price", "sale_price_text", "hash_name"]:
        print(f"  {key}: {item.get(key)}")
else:
    print("No results found.")
    print(json.dumps(data, indent=2)[:500])
