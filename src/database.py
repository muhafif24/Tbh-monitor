import os
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import List, Optional, Dict

log = logging.getLogger(__name__)

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "prices.db"
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the data/ folder and all tables. Migrates existing DBs by adding new columns."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    with closing(_connect()) as conn:
        with conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA cache_size=-8000;
                PRAGMA temp_store=MEMORY;

                CREATE TABLE IF NOT EXISTS tracked_items (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    UNIQUE NOT NULL,
                    color_hex   TEXT    NOT NULL DEFAULT 'FFFFFF',
                    item_type   TEXT    NOT NULL DEFAULT '',
                    item_nameid TEXT,
                    image_url   TEXT,
                    alert_price REAL
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name   TEXT    NOT NULL,
                    price       REAL    NOT NULL,
                    timestamp   TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS items_seen (
                    hash_name  TEXT PRIMARY KEY,
                    item_type  TEXT NOT NULL DEFAULT '',
                    color_hex  TEXT NOT NULL DEFAULT 'FFFFFF',
                    icon_url   TEXT,
                    last_seen  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS items_owned (
                    hash_name   TEXT PRIMARY KEY,
                    count       INTEGER NOT NULL DEFAULT 0,
                    last_synced TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS price_snapshots (
                    item_name   TEXT PRIMARY KEY,
                    ask         REAL,
                    buy_highest REAL,
                    buy_count   INTEGER,
                    timestamp   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS image_cache (
                    hash_name  TEXT PRIMARY KEY,
                    image_data BLOB NOT NULL,
                    cached_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_history_cache (
                    item_name    TEXT PRIMARY KEY,
                    history_json TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_price_history_name_id
                    ON price_history(item_name, id DESC);
            """)
        # Migrate existing databases that predate item_type / item_nameid columns
        for ddl in (
            "ALTER TABLE tracked_items ADD COLUMN item_type   TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE tracked_items ADD COLUMN item_nameid TEXT",
        ):
            try:
                with conn:
                    conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists


# ── tracked_items ─────────────────────────────────────────────────────────────

def add_item(name: str, color_hex: str = "FFFFFF", image_url: Optional[str] = None) -> bool:
    """Add a new item. Returns True on success, False if the name already exists."""
    try:
        with closing(_connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO tracked_items (name, color_hex, image_url) VALUES (?, ?, ?)",
                    (name.strip(), color_hex, image_url),
                )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_item(name: str) -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute("DELETE FROM tracked_items  WHERE name = ?",      (name,))
            conn.execute("DELETE FROM price_history  WHERE item_name = ?", (name,))
            conn.execute("DELETE FROM price_snapshots WHERE item_name = ?", (name,))
            conn.execute("DELETE FROM market_history_cache WHERE item_name = ?", (name,))


def get_all_items() -> list:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM tracked_items ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def get_item_by_name(name: str) -> Optional[dict]:
    """Return a single tracked item by name, or None if not found."""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM tracked_items WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def get_item_count() -> int:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM tracked_items").fetchone()
    return row["c"]


def update_item_metadata(
    name: str,
    color_hex: str,
    item_type: str,
    image_url: Optional[str],
    item_nameid: Optional[str] = None,
) -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "UPDATE tracked_items SET color_hex=?, item_type=?, image_url=?, item_nameid=? WHERE name=?",
                (color_hex, item_type, image_url, item_nameid, name),
            )


def get_alert_price(name: str) -> Optional[float]:
    """Return the configured alert threshold for this item, or None if not set."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT alert_price FROM tracked_items WHERE name = ?", (name,)
        ).fetchone()
    return row["alert_price"] if row else None


def update_alert_price(name: str, price: Optional[float]) -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "UPDATE tracked_items SET alert_price = ? WHERE name = ?",
                (price, name),
            )


# ── price_history ─────────────────────────────────────────────────────────────

def save_price(item_name: str, price: float) -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO price_history (item_name, price, timestamp) VALUES (?, ?, ?)",
                (item_name, price, datetime.now().isoformat()),
            )


def clear_price_history() -> None:
    """Delete all price history rows (call after currency change to avoid bogus trend arrows)."""
    with closing(_connect()) as conn:
        with conn:
            conn.execute("DELETE FROM price_history")


def clear_price_snapshots() -> None:
    """Delete all snapshot rows (call after currency change — stale prices in wrong currency)."""
    with closing(_connect()) as conn:
        with conn:
            conn.execute("DELETE FROM price_snapshots")


def prune_price_history(keep_days: int = 90) -> int:
    """
    Delete price_history rows older than keep_days. Returns number of rows deleted.
    Called at startup to prevent unbounded table growth.
    """
    cutoff = datetime.now() - timedelta(days=keep_days)
    cutoff_str = cutoff.isoformat()
    with closing(_connect()) as conn:
        with conn:
            cursor = conn.execute(
                "DELETE FROM price_history WHERE timestamp < ?", (cutoff_str,)
            )
        return cursor.rowcount


def get_last_price(item_name: str) -> Optional[float]:
    """
    Return the most recently saved price for this item.
    Call BEFORE save_price() to get the previous cycle's price for trend comparison.
    """
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT price FROM price_history WHERE item_name = ? ORDER BY id DESC LIMIT 1",
            (item_name,),
        ).fetchone()
    return row["price"] if row else None


# ── items_seen ────────────────────────────────────────────────────────────────

def upsert_seen_items(items: List[dict]) -> None:
    """
    Bulk upsert into items_seen. Adds new items; updates metadata for existing ones.
    items: list of dicts with keys: hash_name, item_type, color_hex, icon_url.
    Never deletes rows — the table only grows.
    """
    now = datetime.now().isoformat()
    rows = [
        (i["hash_name"], i["item_type"], i["color_hex"], i["icon_url"], now)
        for i in items
    ]
    with closing(_connect()) as conn:
        with conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO items_seen
                    (hash_name, item_type, color_hex, icon_url, last_seen)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )


def get_all_seen_items() -> List[dict]:
    """Return all ever-seen items ordered by hash_name."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT hash_name, item_type, color_hex, icon_url FROM items_seen ORDER BY hash_name"
        ).fetchall()
    return [dict(row) for row in rows]


def get_seen_item_count() -> int:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM items_seen").fetchone()
    return row["c"]


# ── items_owned (from savegame sync) ─────────────────────────────────────────

def replace_owned_items(owned: dict) -> None:
    """
    Replace the entire items_owned table with a fresh savegame sync result.
    owned: {market_hash_name: count}. Full replace — items no longer in the
    save (sold/used) must disappear from the table.
    """
    now = datetime.now().isoformat()
    rows = [(name, count, now) for name, count in owned.items()]
    with closing(_connect()) as conn:
        with conn:
            conn.execute("DELETE FROM items_owned")
            conn.executemany(
                "INSERT INTO items_owned (hash_name, count, last_synced) VALUES (?, ?, ?)",
                rows,
            )


def get_owned_items() -> dict:
    """Return {market_hash_name: count} from the last savegame sync."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT hash_name, count FROM items_owned").fetchall()
    return {row["hash_name"]: row["count"] for row in rows}


# ── price_snapshots (last known ask + buy, restored at startup) ───────────────

def upsert_snapshot_ask(item_name: str, ask: float) -> None:
    now = datetime.now().isoformat()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO price_snapshots (item_name, ask, timestamp)
                VALUES (?, ?, ?)
                ON CONFLICT(item_name) DO UPDATE SET ask=excluded.ask, timestamp=excluded.timestamp
                """,
                (item_name, ask, now),
            )


def upsert_snapshot_buy(item_name: str, buy_highest: Optional[float], buy_count: int) -> None:
    now = datetime.now().isoformat()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO price_snapshots (item_name, buy_highest, buy_count, timestamp)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_name) DO UPDATE SET
                    buy_highest=excluded.buy_highest,
                    buy_count=excluded.buy_count,
                    timestamp=excluded.timestamp
                """,
                (item_name, buy_highest, buy_count, now),
            )


def get_price_snapshot(item_name: str) -> Optional[dict]:
    """Return last cached {ask, buy_highest, buy_count} or None if no snapshot exists."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT ask, buy_highest, buy_count FROM price_snapshots WHERE item_name = ?",
            (item_name,),
        ).fetchone()
    return dict(row) if row else None


def get_all_price_snapshots() -> Dict[str, dict]:
    """Return a dictionary mapping item_name to its price snapshot {ask, buy_highest, buy_count}."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT item_name, ask, buy_highest, buy_count FROM price_snapshots").fetchall()
    return {row["item_name"]: dict(row) for row in rows}


# ── image_cache (static item art — never expires) ─────────────────────────────

def get_uncached_item_images() -> List[dict]:
    """
    Return [{hash_name, icon_url}] for items that have an icon_url in items_seen
    but no entry yet in image_cache. Used by the startup pre-warm worker.
    """
    with closing(_connect()) as conn:
        rows = conn.execute("""
            SELECT s.hash_name, s.icon_url
            FROM items_seen s
            LEFT JOIN image_cache c ON s.hash_name = c.hash_name
            WHERE s.icon_url IS NOT NULL
              AND s.icon_url != ''
              AND c.hash_name IS NULL
            ORDER BY s.hash_name
        """).fetchall()
    return [dict(row) for row in rows]


def get_cached_image(hash_name: str) -> Optional[bytes]:
    """Return cached image bytes, or None if not yet downloaded."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT image_data FROM image_cache WHERE hash_name = ?",
            (hash_name,),
        ).fetchone()
    return bytes(row["image_data"]) if row else None


def save_cached_image(hash_name: str, image_data: bytes) -> None:
    """Persist image bytes. Item art is static — no TTL needed."""
    now = datetime.now().isoformat()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO image_cache (hash_name, image_data, cached_at)
                VALUES (?, ?, ?)
                ON CONFLICT(hash_name) DO UPDATE SET
                    image_data=excluded.image_data,
                    cached_at=excluded.cached_at
                """,
                (hash_name, image_data, now),
            )


def save_market_history_cache(item_name: str, history: list) -> None:
    """Save JSON-serialized history rows to the database cache."""
    now = datetime.now().isoformat()
    history_json = json.dumps(history)
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO market_history_cache (item_name, history_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(item_name) DO UPDATE SET
                    history_json=excluded.history_json,
                    updated_at=excluded.updated_at
                """,
                (item_name, history_json, now),
            )


def get_all_market_history_cache() -> Dict[str, dict]:
    """Batch-load all cached market histories in a single query.
    Returns {item_name: {"history": list, "updated_at": str}}.
    """
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT item_name, history_json, updated_at FROM market_history_cache"
        ).fetchall()
    result: Dict[str, dict] = {}
    for row in rows:
        try:
            result[row["item_name"]] = {
                "history": json.loads(row["history_json"]),
                "updated_at": row["updated_at"],
            }
        except Exception as exc:
            log.warning("Failed to decode cached history JSON for %s: %s", row["item_name"], exc)
    return result


def get_market_history_cache(item_name: str) -> Optional[dict]:
    """
    Retrieve cached history list and updated_at timestamp.
    Returns: {"history": list, "updated_at": str} or None if not cached.
    """
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT history_json, updated_at FROM market_history_cache WHERE item_name = ?",
            (item_name,),
        ).fetchone()
    if row:
        try:
            history = json.loads(row["history_json"])
            return {"history": history, "updated_at": row["updated_at"]}
        except Exception as exc:
            log.warning("Failed to decode cached history JSON for %s: %s", item_name, exc)
    return None


# ── Maintenance ───────────────────────────────────────────────────────────────

def run_optimize() -> None:
    """Run PRAGMA optimize to refresh query planner statistics. Call at app shutdown."""
    with closing(_connect()) as conn:
        conn.execute("PRAGMA optimize")
