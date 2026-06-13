"""
Headless backend endurance test — without GUI.
Run: python -m tests.headless_endurance
Duration: ~5 minutes (3 price cycles + 1 listing fetch)
"""
import logging
import os
import sys
import tempfile
import threading
import time

# Setup logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Windows cp1252 fix
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
log = logging.getLogger("endurance")

# Use temp DB to avoid corrupting user data
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()

import src.database as db
db._DB_PATH = _TMP_DB.name

from dotenv import load_dotenv
load_dotenv()

from src.database import init_db, add_item, get_all_items, get_last_price, save_price, get_item_count
from src.worker import PriceWorker, ListingWorker

ITEM = "Frozen Orb (Immortal) A"
RESULTS = {"price_ok": 0, "price_err": 0, "listing_ok": False}

stop_event = threading.Event()


def on_price(name, result):
    if result.get("status") == "OK":
        RESULTS["price_ok"] += 1
        price = result["price"]
        save_price(name, price)
        last = get_last_price(name)
        log.info(f"[PRICE] {name} -> Rp {price:,.0f}  (last={last})")
    else:
        RESULTS["price_err"] += 1
        log.warning(f"[PRICE ERR] {name} -> {result.get('status')}")


def on_listing(name, history, image_url, buy_orders, color_hex, item_type, item_nameid):
    RESULTS["listing_ok"] = True
    img_flag = "OK" if image_url else "NONE"
    log.info(
        f"[LISTING] {name} | history={len(history)} pts | img={img_flag} "
        f"| buy={buy_orders.get('highest_price')} | color={color_hex} | type={item_type!r}"
    )


def run():
    log.info("=" * 60)
    log.info("  TBH Market Tracker — Headless Endurance Test")
    log.info("=" * 60)

    # ── 1. Init DB ──────────────────────────────────────────────
    log.info("[SETUP] Init DB (temp)")
    init_db()
    added = add_item(ITEM)
    assert added, "add_item failed"
    assert get_item_count() == 1
    log.info(f"[SETUP] Item added: {ITEM}")

    # ── 2. Listing worker (startup) ──────────────────────────────
    log.info("[LISTING] Starting listing worker (metadata + graph)...")
    listing_done = threading.Event()

    def _on_listing_wrap(*args):
        on_listing(*args)
        listing_done.set()

    lw = ListingWorker([ITEM], _on_listing_wrap, stop_event, fetch_metadata=True)
    lw.start()
    listing_done.wait(timeout=120)
    lw.join(timeout=5)
    if RESULTS["listing_ok"]:
        log.info("[LISTING] PASS - Listing worker completed without errors")
    else:
        log.warning("[LISTING] WARN - Listing worker timeout or error -- check connection")

    # ── 3. Price cycles (3×) ─────────────────────────────────────
    for cycle in range(1, 4):
        log.info(f"[CYCLE {cycle}/3] Starting price worker...")
        pw = PriceWorker([ITEM], on_price, stop_event)
        pw.start()
        pw.join(timeout=90)
        log.info(f"[CYCLE {cycle}/3] Completed. Waiting 65 seconds before next cycle...")
        if cycle < 3:
            for _ in range(65):
                if stop_event.is_set():
                    break
                time.sleep(1)

    # ── 4. DB integrity check ────────────────────────────────────
    log.info("[DB] Check database integrity...")
    last = get_last_price(ITEM)
    all_items = get_all_items()
    assert len(all_items) == 1
    log.info(f"[DB] last_price={last}  items={len(all_items)}")

    # ── 5. Hasil ─────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  ENDURANCE TEST RESULTS (BACKEND)")
    log.info(f"  Price OK  : {RESULTS['price_ok']}")
    log.info(f"  Price ERR : {RESULTS['price_err']}")
    listing_status = "PASS" if RESULTS["listing_ok"] else "FAIL"
    log.info(f"  Listing   : {listing_status}")
    log.info(f"  DB last   : {last}")
    total = RESULTS["price_ok"] + RESULTS["price_err"]
    rate = (RESULTS["price_ok"] / total * 100) if total else 0
    log.info(f"  Success rate: {rate:.0f}% ({RESULTS['price_ok']}/{total})")
    if rate >= 80:
        log.info("  VERDICT: PASS")
    else:
        log.info("  VERDICT: FAIL -- success rate < 80% or item SOLD_OUT")
    log.info("=" * 60)

    # Cleanup
    try:
        os.unlink(_TMP_DB.name)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        stop_event.set()
        log.info("Test terminated by user (Ctrl+C).")
