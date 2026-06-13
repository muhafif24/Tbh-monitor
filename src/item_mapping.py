"""
Item mapping — link Steam market hash names to in-game ItemKeys.

Data source: https://taskbarhero.wiki/data/items.json (5,900+ game items).
Downloaded ONCE and cached permanently at data/tbh_items.json — no TTL,
re-downloaded only if the cache file is missing (or via force=True).
This hits taskbarhero.wiki, NOT Steam, so it does not affect Steam rate limits.

Naming rules (verified against the live Steam market catalog):
  - Materials / non-gear:  hash name == item name           e.g. "Soulstone - Normal"
  - Gear:                  "<name> (<Grade>) <A|B>"          e.g. "Frozen Orb (Immortal) A"
    Same name+grade has two ItemKeys (e.g. 424041/424042) — sorted ascending,
    the lower id is variant A, the higher is variant B.
"""
import os
import re
import json
import logging
from typing import Dict, List

import requests

log = logging.getLogger(__name__)

_ITEMS_URL  = "https://taskbarhero.wiki/data/items.json"
_DATA_DIR   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CACHE_PATH = os.path.join(_DATA_DIR, "tbh_items.json")

# taskbarhero.wiki returns 403 without a browser User-Agent
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}

# "Frozen Orb (Immortal) A" → name + grade + variant
_GEAR_NAME_RE = re.compile(
    r"^(?P<name>.+?) "
    r"\((?P<grade>Common|Uncommon|Rare|Legendary|Immortal|Arcana|Beyond|Celestial|Divine|Cosmic)\) "
    r"(?P<var>[AB])$"
)


def get_game_items(force: bool = False) -> List[dict]:
    """Load the game item list from cache, downloading once if missing."""
    if not force and os.path.exists(_CACHE_PATH):
        try:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("tbh_items.json cache corrupt (%s) — re-downloading.", exc)

    log.info("Downloading game item list from taskbarhero.wiki (one-time)...")
    resp = requests.get(_ITEMS_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    items = resp.json()

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    log.info("Game item list cached: %d items.", len(items))
    return items


def _english_name(item: dict) -> str:
    name = item.get("name")
    if isinstance(name, dict):
        return name.get("en-US", "") or ""
    return str(name) if name else ""


def build_market_to_keys(market_names: List[str], force: bool = False) -> Dict[str, List[int]]:
    """
    For each Steam market hash name, find the matching in-game ItemKey(s).
    Names that can't be matched are omitted (e.g. items.json out of date).
    """
    game_items = get_game_items(force=force)

    # Index game items: plain name → ids, and (name, grade) → sorted ids
    by_name: Dict[str, List[int]] = {}
    by_name_grade: Dict[tuple, List[int]] = {}
    for it in game_items:
        n = _english_name(it)
        if not n:
            continue
        by_name.setdefault(n, []).append(it["id"])
        grade = (it.get("grade") or "").upper()
        by_name_grade.setdefault((n, grade), []).append(it["id"])
    for ids in by_name_grade.values():
        ids.sort()

    result: Dict[str, List[int]] = {}
    for market_name in market_names:
        m = _GEAR_NAME_RE.match(market_name)
        if m:
            ids = by_name_grade.get((m.group("name"), m.group("grade").upper()), [])
            variant_idx = 0 if m.group("var") == "A" else 1
            if len(ids) > variant_idx:
                result[market_name] = [ids[variant_idx]]
        elif market_name in by_name:
            result[market_name] = list(by_name[market_name])

    unmatched = len(market_names) - len(result)
    if unmatched:
        log.info("Item mapping: %d/%d market names matched (%d unmatched).",
                 len(result), len(market_names), unmatched)
    return result


def owned_by_market_name(
    market_names: List[str],
    owned_counts: Dict[int, int],
    force: bool = False,
) -> Dict[str, int]:
    """
    Combine save-file ownership with the market name list.
    Returns {market_hash_name: owned_count} for names owned at least once.
    NOTE: Only maps items already in market_names (items_seen).
    Use key_to_market_names() instead to also discover sold-out owned items.
    """
    mapping = build_market_to_keys(market_names, force=force)
    result: Dict[str, int] = {}
    for market_name, keys in mapping.items():
        total = sum(owned_counts.get(k, 0) for k in keys)
        if total > 0:
            result[market_name] = total
    return result


def key_to_market_names(
    owned_counts: Dict[int, int],
    force: bool = False,
) -> Dict[str, int]:
    """
    Build {market_hash_name: count} directly from save-file ItemKeys.

    Unlike owned_by_market_name(), this does NOT require items to already be in
    items_seen — it works for sold-out items that have never appeared in a catalog
    fetch (zero sell listings on Steam).

    Naming rules (same as Steam market):
      - Gear (2 IDs share same name+grade): "<name> (<Grade>) A/B"
      - Material / non-gear (single ID): plain item name
    """
    game_items = get_game_items(force=force)

    by_id: Dict[int, dict] = {it["id"]: it for it in game_items if it.get("id")}

    # Group IDs by (english_name, GRADE) to detect A/B gear pairs
    by_name_grade: Dict[tuple, List[int]] = {}
    for it in game_items:
        n = _english_name(it)
        grade = (it.get("grade") or "").upper()
        if n and grade:
            by_name_grade.setdefault((n, grade), []).append(it["id"])
    for ids in by_name_grade.values():
        ids.sort()

    result: Dict[str, int] = {}
    unmatched = 0

    for item_key, count in owned_counts.items():
        it = by_id.get(item_key)
        if not it:
            unmatched += 1
            log.debug("ItemKey %d not found in tbh_items.json — skipped.", item_key)
            continue

        n = _english_name(it)
        raw_grade = (it.get("grade") or "").upper()
        peer_ids = by_name_grade.get((n, raw_grade), [])

        if len(peer_ids) >= 2:
            # Gear with A/B variants — lower ID = A, higher = B
            if item_key not in peer_ids:
                unmatched += 1
                continue
            grade_cap = raw_grade[0] + raw_grade[1:].lower()  # "ARCANA" → "Arcana"
            var = "A" if peer_ids.index(item_key) == 0 else "B"
            market_name = f"{n} ({grade_cap}) {var}"
        else:
            # Material / non-gear: market name = plain item name
            market_name = n

        result[market_name] = result.get(market_name, 0) + count

    log.info(
        "key_to_market_names: %d ItemKeys → %d market names (%d unmatched).",
        len(owned_counts), len(result), unmatched,
    )
    return result
