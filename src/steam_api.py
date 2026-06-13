import re
import json
import time
import logging
import urllib.parse
from typing import Optional
import requests

from . import config as _cfg

log = logging.getLogger(__name__)

APP_ID   = "3678970"
BASE_URL = "https://steamcommunity.com/market"
HISTORY_POINTS = 300
MAX_TRIES = 5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _encode_name(name: str) -> str:
    if not name or not name.strip():
        raise ValueError("Item name must not be empty.")
    return urllib.parse.quote_plus(name.strip()).replace("~", "%7E")


def _get_retry_delay(response: requests.Response, tries: int) -> float:
    """Read retry penalty duration from a 429 response in priority order."""
    try:
        body = response.json()
        if isinstance(body, dict) and "retry_after" in body:
            return float(body["retry_after"])
    except Exception:
        pass

    for header in ("Retry-After", "X-Retry-After"):
        value = response.headers.get(header)
        if value:
            try:
                return float(value)
            except ValueError:
                pass

    return float(2 ** tries) * 5  # 5, 10, 20, 40, 80s — Steam needs 30+ s to reset


def _parse_idr(raw: str) -> Optional[float]:
    """
    Parse a Steam price string → float. Handles IDR, USD, EUR, ARS, etc.

    Strategy: if the string ends with a separator (. or ,) followed by exactly 1-2 digits,
    treat those as the decimal fraction. Otherwise strip all separators (thousands only).

    Examples:
      "Rp 1.750"       → 1750.0   (dot = thousands, 3 decimal digits → no match)
      "Rp 1.200.000"   → 1200000.0
      "$14.04"         → 14.04    (dot = decimal, 2 digits → match)
      "€14,04"         → 14.04
      "ARS$ 14.045,68" → 14045.68
    """
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.,]", "", raw.strip())
    if not cleaned:
        return None
    m = re.match(r"^(.*)[.,](\d{1,2})$", cleaned)
    if m:
        integer_part = re.sub(r"[.,]", "", m.group(1))
        return float(f"{integer_part or '0'}.{m.group(2)}")
    return float(re.sub(r"[.,]", "", cleaned))


class SteamMarketAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def _request(self, url: str, headers: Optional[dict] = None) -> Optional[requests.Response]:
        for tries in range(MAX_TRIES):
            try:
                response = self.session.get(url, timeout=15, headers=headers)
            except requests.exceptions.RequestException as e:
                delay = 1 + tries * 3
                log.warning("Network error (try %d/%d): %s — retry in %ds.", tries + 1, MAX_TRIES, e, delay)
                time.sleep(delay)
                continue

            status = response.status_code

            if 200 <= status < 300:
                return response

            elif status == 429:
                delay = _get_retry_delay(response, tries)
                log.warning("Rate limited 429 (try %d/%d) — sleeping %.1fs.", tries + 1, MAX_TRIES, delay)
                time.sleep(delay)
                continue

            elif status in (500, 502):
                delay = 1 + tries * 3
                log.warning("Server error %d (try %d/%d) — retry in %ds.", status, tries + 1, MAX_TRIES, delay)
                time.sleep(delay)
                continue

            elif status in (403, 404):
                log.warning("Unrecoverable error %d for URL: %s", status, url)
                return None

            else:
                log.error("Unexpected status %d for URL: %s", status, url)
                return None

        log.error("Max retries (%d) reached for: %s", MAX_TRIES, url)
        return None

    def get_price(self, name: str) -> dict:
        """
        Returns one of:
          {"status": "OK",       "price": 15000.0, "median_price": 12000.0, "volume": 60}
          {"status": "SOLD_OUT"}
          {"status": "ERROR"}
        median_price and volume may be None if Steam doesn't return them.
        """
        encoded = _encode_name(name)
        url = f"{BASE_URL}/priceoverview/?appid={APP_ID}&currency={_cfg.get_currency_code()}&market_hash_name={encoded}"
        response = self._request(url)

        if response is None:
            return {"status": "ERROR"}

        try:
            data = response.json()
        except ValueError:
            return {"status": "ERROR"}

        if not data.get("success"):
            return {"status": "ERROR"}

        raw = data.get("lowest_price")
        if not raw:
            return {"status": "SOLD_OUT"}

        price = _parse_idr(raw)
        if price is None:
            return {"status": "ERROR"}

        median_price = None
        raw_median = data.get("median_price")
        if raw_median:
            median_price = _parse_idr(raw_median)

        volume = None
        raw_volume = data.get("volume")
        if raw_volume:
            try:
                volume = int(str(raw_volume).replace(",", ""))
            except ValueError:
                pass

        return {"status": "OK", "price": price, "median_price": median_price, "volume": volume}

    def get_item_metadata(self, name: str) -> dict:
        """
        Returns {"color": "E8695A", "item_type": "Orb - Lv. 15", "icon_url": "https://..."}
        from search/render. Defaults: color="FFFFFF", item_type="", icon_url=None.

        icon_url is a full CDN URL for the item's 128x128 thumbnail.
        Only populated when search/render returns an exact market_hash_name match.
        Steam's listing HTML no longer embeds image data (RSC redesign, 2025).
        """
        encoded = _encode_name(name)
        url = f"{BASE_URL}/search/render/?query={encoded}&appid={APP_ID}&count=1&norender=1"
        response = self._request(url)

        result: dict = {"color": "FFFFFF", "item_type": "", "icon_url": None}
        if response is None:
            return result

        try:
            data = response.json()
        except ValueError:
            return result

        if not data.get("success") or not data.get("results"):
            return result

        desc = data["results"][0].get("asset_description", {})
        result["color"] = desc.get("name_color") or "FFFFFF"
        result["item_type"] = desc.get("type") or ""

        # Only use icon from an exact name match (search is fuzzy; wrong icon is misleading)
        if desc.get("market_hash_name") == name:
            raw_icon = desc.get("icon_url", "")
            if raw_icon:
                result["icon_url"] = (
                    f"https://community.fastly.steamstatic.com/economy/image/{raw_icon}/128x128"
                )

        return result

    def get_listing_data(self, name: str) -> dict:
        """
        Returns:
          {"history": [[date, price, volume], ...], "image_url": "...", "item_nameid": "12345678" | None}
        history is sliced to the last HISTORY_POINTS entries.
        Graph prices are in USD (Steam's default without login).
        item_nameid is required for get_buy_orders().
        """
        encoded = _encode_name(name)
        url = f"{BASE_URL}/listings/{APP_ID}/{encoded}"
        response = self._request(url)

        result = {"history": [], "image_url": None, "item_nameid": None}
        if response is None:
            return result

        html = response.text

        m = re.search(r"var line1=(\[.*?\]);", html, re.DOTALL)
        if m:
            try:
                history = json.loads(m.group(1))
                result["history"] = history[-HISTORY_POINTS:]
            except json.JSONDecodeError:
                log.warning("Failed to parse line1 for item: %s", name)

        m = re.search(r'<img[^>]+id="[^"]+_image"[^>]+src="([^"]+)"', html)
        if m:
            result["image_url"] = m.group(1)

        m = re.search(r'Market\.LoadOrderSpread\(\s*(\d+)', html)
        if m:
            result["item_nameid"] = m.group(1)
        else:
            # Fallback pattern used on some Steam pages
            m = re.search(r'CreateItemHistogram\(\s*(\d+)', html)
            if m:
                result["item_nameid"] = m.group(1)

        return result

    def get_orderbook(self, name: str) -> dict:
        """
        Fetch the buy/sell order summary from Steam's NEW orderbook endpoint
        (market redesign 2025+). Works with the market hash name directly —
        no item_nameid needed (the old itemordershistogram path is dead).

        Protocol (reverse-engineered from Steam's SSR frontend):
          GET /market/orderbook?q=Load&qp=[appid,"<hash name>"]
          Header: x-valve-request-type: queryAction

        Returns:
          {"highest_buy": float|None, "buy_count": int,
           "lowest_sell": float|None, "sell_count": int, "currency": int|None}
        Amounts are converted from Steam's integer representation (value × 100).

        NOTE: for anonymous sessions the response currency follows Steam's
        geo-IP, not our currency setting — callers must check "currency"
        before displaying values with the selected currency symbol.
        """
        qp = json.dumps([int(APP_ID), name.strip()])
        url = f"{BASE_URL}/orderbook?q=Load&qp={urllib.parse.quote(qp)}"
        response = self._request(url, headers={"x-valve-request-type": "queryAction"})

        result = {
            "highest_buy": None, "buy_count": 0,
            "lowest_sell": None, "sell_count": 0,
            "currency": None,
        }
        if response is None:
            return result

        try:
            payload = response.json()
        except ValueError:
            return result

        if not payload.get("success") or not isinstance(payload.get("data"), dict):
            return result

        data = payload["data"]

        def _amount(key: str) -> Optional[float]:
            raw = data.get(key)
            try:
                value = int(raw)
            except (ValueError, TypeError):
                return None
            return value / 100 if value > 0 else None

        result["highest_buy"] = _amount("amtMaxBuyOrder")
        result["lowest_sell"] = _amount("amtMinSellOrder")
        result["buy_count"]   = int(data.get("cBuyOrders") or 0)
        result["sell_count"]  = int(data.get("cSellOrders") or 0)
        currency = data.get("eCurrency")
        if currency is not None:
            try:
                result["currency"] = int(currency)
            except (ValueError, TypeError):
                pass
        return result

    def get_buy_orders(self, item_nameid: str) -> dict:
        """
        Returns {"highest_price": float | None, "count": int}.
        Steam stores prices as integer × 100 (smallest currency unit, i.e. IDR sen).
        So raw value 11184200 → Rp 111,842.
        """
        url = (
            f"https://steamcommunity.com/market/itemordershistogram"
            f"?country=ID&language=english&currency={_cfg.get_currency_code()}"
            f"&item_nameid={item_nameid}&two_factor=0"
        )
        response = self._request(url)
        result = {"highest_price": None, "count": 0}
        if response is None:
            return result

        try:
            data = response.json()
        except ValueError:
            return result

        if not data.get("success"):
            return result

        raw_price = data.get("highest_buy_order")
        raw_count = data.get("buy_order_count", "0")

        if raw_price:
            try:
                result["highest_price"] = int(raw_price) / 100
            except (ValueError, TypeError):
                pass

        try:
            result["count"] = int(str(raw_count).replace(",", ""))
        except (ValueError, TypeError):
            pass

        return result
