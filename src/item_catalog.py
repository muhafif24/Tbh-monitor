"""
Item catalog — bulk fetch + offline database of all TBH tradeable items.

Cache strategy (Opsi C):
  - Live catalog cached to data/catalog_cache.json (24-hour TTL).
  - Startup: load cache if fresh → 0 requests; stale/missing → fetch 3 pages (~9s).
  - Manual "↻ Catalog" button: force-fetch regardless of TTL.

Offline seen-items DB (Opsi A — SQLite):
  - items_seen table in data/prices.db — grows over time, never shrinks.
  - Every catalog fetch/load merges new items into this table via upsert.
  - Items no longer in the live catalog are kept with available=False (sold out).
  - Dialog shows all seen items; sold-out ones are grayed with a "[sold out]" badge.
"""
import json
import os
import time
import logging
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from .steam_api import APP_ID, SteamMarketAPI
from .database import upsert_seen_items, get_all_seen_items, get_owned_items

log = logging.getLogger(__name__)

_SEARCH_URL      = "https://steamcommunity.com/market/search/render/"
_PAGE_SIZE       = 100
_PAGE_DELAY      = 6.0   # seconds between pages
_CACHE_TTL_H     = 24    # hours before catalog cache is considered stale
_MIN_CATALOG_SIZE = 50   # if cache has fewer items, treat as incomplete → force re-fetch

_DATA_DIR   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CACHE_PATH = os.path.join(_DATA_DIR, "catalog_cache.json")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class CatalogItem:
    """Item currently listed on the Steam market (has active sell listings)."""
    hash_name:     str
    item_type:     str
    color_hex:     str
    icon_url:      Optional[str]
    sell_listings: int


@dataclass
class SeenItem:
    """
    Item ever seen in any catalog fetch.
    available=True  → in current live catalog (has active listings).
    available=False → was seen before but currently sold out.
    owned > 0       → player has this many in their savegame (last sync).
    """
    hash_name: str
    item_type: str
    color_hex: str
    icon_url:  Optional[str]
    available: bool
    owned:     int = 0


# ── Module-level state ────────────────────────────────────────────────────────

_lock  = threading.Lock()
_cache: List[CatalogItem] = []
_ready = False
_fetching = False   # True while a catalog fetch is hitting Steam (pause other requests)


# ── Catalog cache I/O (JSON, 24h TTL) ────────────────────────────────────────

def _save_cache(items: List[CatalogItem]) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "complete": True,   # only complete fetches are ever saved
        "items": [asdict(i) for i in items],
    }
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        log.info("Catalog cache saved: %d items.", len(items))
    except Exception as exc:
        log.warning("Failed to save catalog cache: %s", exc)


def _load_cache() -> Tuple[List[CatalogItem], Optional[datetime]]:
    if not os.path.exists(_CACHE_PATH):
        return [], None
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not payload.get("complete"):
            # Old-format or partial cache (saved before the completeness guard) — discard
            log.warning("Catalog cache is partial/old format — ignoring it.")
            return [], None
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        items = [CatalogItem(**d) for d in payload["items"]]
        return items, fetched_at
    except Exception as exc:
        log.warning("Failed to load catalog cache: %s", exc)
        return [], None


def _is_fresh(fetched_at: Optional[datetime]) -> bool:
    if fetched_at is None:
        return False
    return datetime.now() - fetched_at < timedelta(hours=_CACHE_TTL_H)


def cache_age_str() -> str:
    """Human-readable cache age, e.g. '3h 12m ago'."""
    _, fetched_at = _load_cache()
    if fetched_at is None:
        return "none"
    delta = datetime.now() - fetched_at
    total_minutes = int(delta.total_seconds() / 60)
    if total_minutes < 1:
        return "just now"
    hours, mins = divmod(total_minutes, 60)
    return f"{hours}h {mins}m ago" if hours else f"{mins}m ago"


# ── Seen-items DB (SQLite) ────────────────────────────────────────────────────

def _merge_seen(catalog_items: List[CatalogItem]) -> None:
    """
    Upsert catalog_items into the items_seen SQLite table.
    Adds new items; updates metadata for existing ones. Never deletes rows.
    """
    rows = [
        {
            "hash_name": item.hash_name,
            "item_type": item.item_type,
            "color_hex": item.color_hex,
            "icon_url":  item.icon_url,
        }
        for item in catalog_items
    ]
    upsert_seen_items(rows)
    log.info("Seen-items DB: merged %d items.", len(rows))


def seen_counts() -> Tuple[int, int]:
    """Returns (available_now, total_ever_seen)."""
    rows = get_all_seen_items()
    current_names = {item.hash_name for item in get_catalog()}
    available = sum(1 for r in rows if r["hash_name"] in current_names)
    return available, len(rows)


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_catalog() -> List[CatalogItem]:
    """
    Fetch all tradeable TBH items from Steam (multiple pages).
    Uses SteamMarketAPI._request() for proper 429 backoff + retry.

    Completeness guarantee:
      - JSON cache is ONLY written when ALL pages were fetched successfully.
      - A partial result (interrupted by rate limit) is merged into the
        seen-items DB and in-memory state, but never poisons the 24h cache —
        so the next startup/refresh will retry the full fetch.
    """
    global _cache, _ready, _fetching

    api   = SteamMarketAPI()   # has retry + 429 backoff built-in
    items: List[CatalogItem] = []
    start = 0
    total = 0
    complete = False

    with _lock:
        _fetching = True

    while True:
        url = (
            f"{_SEARCH_URL}?appid={APP_ID}&norender=1"
            f"&count={_PAGE_SIZE}&start={start}"
        )
        resp = api._request(url)

        if resp is None:
            log.warning("Catalog fetch gave up at start=%d (all retries failed).", start)
            break

        try:
            data = resp.json()
        except ValueError:
            log.warning("Catalog: invalid JSON at start=%d.", start)
            break

        results = data.get("results", [])
        total   = data.get("total_count", 0)

        if start == 0:
            log.info("Catalog: Steam total_count=%d for appid=%s.", total, APP_ID)

        for r in results:
            desc      = r.get("asset_description", {})
            hash_name = r.get("hash_name", "")
            if not hash_name:
                continue
            raw_icon = desc.get("icon_url", "")
            items.append(CatalogItem(
                hash_name=hash_name,
                item_type=desc.get("type") or "",
                color_hex=desc.get("name_color") or "FFFFFF",
                icon_url=(
                    f"https://community.fastly.steamstatic.com/economy/image/{raw_icon}/128x128"
                    if raw_icon else None
                ),
                sell_listings=int(r.get("sell_listings") or 0),
            ))

        actual = len(results)
        log.info("Catalog page start=%d: %d items so far (+%d this page).", start, len(items), actual)
        start += actual

        if not results or start >= total:
            complete = True
            break

        time.sleep(_PAGE_DELAY)

    with _lock:
        _fetching = False

    if items:
        _merge_seen(items)   # seen DB always benefits, even from partial data
        with _lock:
            _cache = items
            _ready = True
        if complete:
            _save_cache(items)
            log.info("Catalog ready: %d/%d tradeable TBH items (complete).", len(items), total)
        else:
            log.warning(
                "Catalog PARTIAL: %d/%d items — cache NOT saved, will retry on next refresh.",
                len(items), total,
            )
    else:
        log.warning("Catalog fetch returned 0 items — keeping previous cache.")

    return items


def get_or_fetch_catalog(force: bool = False) -> List[CatalogItem]:
    """
    Main entry point. Uses JSON cache if fresh (< 24h), else fetches from Steam.
    force=True → always fetch (manual refresh button).
    Always merges result into SQLite seen DB.
    """
    if not force:
        cached_items, fetched_at = _load_cache()
        if cached_items and _is_fresh(fetched_at) and len(cached_items) >= _MIN_CATALOG_SIZE:
            log.info("Catalog from cache: %d items (%s).", len(cached_items), cache_age_str())
            with _lock:
                global _cache, _ready
                _cache = cached_items
                _ready = True
            _merge_seen(cached_items)
            return cached_items
        elif cached_items and len(cached_items) < _MIN_CATALOG_SIZE:
            log.warning(
                "Catalog cache has only %d items (< %d threshold) — forcing fresh fetch.",
                len(cached_items), _MIN_CATALOG_SIZE,
            )

    return fetch_catalog()


# ── Startup helper ────────────────────────────────────────────────────────────

def load_cache_only() -> List[CatalogItem]:
    """
    Load catalog from JSON cache into memory WITHOUT fetching from Steam.
    Safe to call at startup — zero network requests.
    If no cache exists, in-memory catalog stays empty but items_seen DB is still usable.
    """
    global _cache, _ready
    cached_items, fetched_at = _load_cache()
    if cached_items:
        with _lock:
            _cache = cached_items
            _ready = True
        _merge_seen(cached_items)
        age = cache_age_str()
        log.info("Catalog loaded from cache: %d items (%s).", len(cached_items), age)
    else:
        log.info("No catalog cache — Add Item dialog will use seen_items DB only.")
    return cached_items


# ── Accessors ─────────────────────────────────────────────────────────────────

def get_catalog() -> List[CatalogItem]:
    """Current live catalog snapshot (may be empty before first load)."""
    with _lock:
        return list(_cache)


def get_item(hash_name: str) -> Optional[CatalogItem]:
    """Look up one item in the live catalog by hash_name."""
    with _lock:
        for item in _cache:
            if item.hash_name == hash_name:
                return item
    return None


def get_seen_catalog() -> List[SeenItem]:
    """
    All ever-seen items from SQLite, enriched with current availability
    and owned count from the last savegame sync.
    Sort: available first (A→Z), then sold-out (A→Z).
    """
    rows = get_all_seen_items()
    current_names = {item.hash_name for item in get_catalog()}
    owned = get_owned_items()

    result = [
        SeenItem(
            hash_name=row["hash_name"],
            item_type=row["item_type"],
            color_hex=row["color_hex"],
            icon_url=row.get("icon_url"),
            available=row["hash_name"] in current_names,
            owned=owned.get(row["hash_name"], 0),
        )
        for row in rows
    ]
    result.sort(key=lambda x: (not x.available, x.hash_name.lower()))
    return result


def is_ready() -> bool:
    with _lock:
        return _ready


def is_fetching() -> bool:
    """True while a catalog fetch is in progress — pause other Steam requests."""
    with _lock:
        return _fetching
