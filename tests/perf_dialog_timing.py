"""
Automated timing test for AddItemDialog.
Opens the real dialog with real catalog data, measures per-phase timing,
simulates filter tab clicks, then closes everything automatically.
Run: python -m tests.perf_dialog_timing
"""
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
log = logging.getLogger("perf_timing")

from src.database import init_db
from src import item_catalog

init_db()

# ── 1. Catalog load ──────────────────────────────────────────────────────────
t0 = time.perf_counter()
catalog = item_catalog.load_cache_only()
log.info("[1] load_cache_only:       %6.1f ms  (%d items)", (time.perf_counter()-t0)*1000, len(catalog))

# ── 2. get_seen_catalog — cold ───────────────────────────────────────────────
item_catalog.invalidate_seen_catalog_cache()
t0 = time.perf_counter()
seen = item_catalog.get_seen_catalog()
log.info("[2] get_seen_catalog COLD: %6.1f ms  (%d items)", (time.perf_counter()-t0)*1000, len(seen))

# ── 3. get_seen_catalog — warm ───────────────────────────────────────────────
t0 = time.perf_counter()
seen = item_catalog.get_seen_catalog()
log.info("[3] get_seen_catalog WARM: %6.1f ms", (time.perf_counter()-t0)*1000)

# ── 4. GUI dialog timing ─────────────────────────────────────────────────────
log.info("[4] Starting GUI timing test...")
import customtkinter as ctk
from src.gui.add_dialog import AddItemDialog

root = ctk.CTk()
root.withdraw()

results = {}
t_dialog_start = [0.0]

def open_dialog():
    t_dialog_start[0] = time.perf_counter()
    dlg = AddItemDialog(root, current_names=[], on_confirm=lambda n: None, catalog=seen)
    results["init_ms"] = (time.perf_counter() - t_dialog_start[0]) * 1000

    def check_loaded():
        if not dlg.winfo_exists():
            root.quit()
            return
        # Build is done when loading_label is None and items are present
        if dlg._loading_label is None and len(dlg._item_buttons) > 0:
            results["total_build_ms"] = (time.perf_counter() - t_dialog_start[0]) * 1000
            run_filter_tests(dlg)
        else:
            dlg.after(30, check_loaded)

    dlg.after(30, check_loaded)

def run_filter_tests(dlg):
    filter_times = {}
    for filt in ("Listed", "Sold out", "Owned", "All"):
        dlg._filter = filt
        t = time.perf_counter()
        dlg._apply_search_filter()
        filter_times[filt] = (time.perf_counter() - t) * 1000

    results["filter_ms"] = filter_times

    # Search test
    search_times = {}
    for q in ("fire", "orb", "chain", ""):
        dlg._search_var.set(q)
        dlg._filter = "All"
        t = time.perf_counter()
        dlg._apply_search_filter()
        search_times[f"'{q}'" if q else "'(clear)'"] = (time.perf_counter() - t) * 1000

    results["search_ms"] = search_times

    dlg.after(800, dlg.destroy)   # longer delay so CTkToplevel internal callbacks settle
    root.after(1200, root.quit)

root.after(0, open_dialog)
root.mainloop()

# ── 5. Report ────────────────────────────────────────────────────────────────
log.info("")
log.info("=" * 55)
log.info("  TIMING RESULTS")
log.info("=" * 55)
log.info("  Dialog __init__ (visible to user): %6.1f ms  %s",
         results.get("init_ms", 0),
         "OK" if results.get("init_ms", 999) < 300 else "SLOW")
log.info("  Full list build (all items):       %6.1f ms  %s",
         results.get("total_build_ms", 0),
         "OK" if results.get("total_build_ms", 9999) < 800 else "SLOW")
log.info("")
log.info("  Filter tab switch:")
for filt, ms in results.get("filter_ms", {}).items():
    log.info("    %-12s %6.1f ms  %s", filt, ms, "OK" if ms < 50 else "SLOW")
log.info("")
log.info("  Search query:")
for q, ms in results.get("search_ms", {}).items():
    log.info("    %-14s %6.1f ms  %s", q, ms, "OK" if ms < 50 else "SLOW")
log.info("=" * 55)
