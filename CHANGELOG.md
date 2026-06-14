# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Performance (2026-06-14 — Save Inspector Detail Card Pre-creation)
- Eliminated widget destroy-and-recreate cycle in `SaveInspectorWindow._update_detail_card()`. Previously, every item click destroyed all ~10 CTk widgets in the right panel and rebuilt them from scratch (50-200ms lag). Now all detail panel widgets (image label, name label, subtitle, spec frame with 4 value labels, description) are created once in `_build_detail_panel()` at window open time and updated via `.configure()` on each selection — switching items is instant. `_show_empty_detail_placeholder()` uses `pack_forget()` + `place()` to toggle visibility instead of destroying widgets.

### Performance (2026-06-14 — Matplotlib Quick Wins)
- Fixed graph being fully redrawn on every 60-second price update even when history data had not changed. Exchange rate (IDR/USD scaling) is derived from the current price, so the graph only needs to redraw when the price actually changes. Added `prev_price` check in `update_price()` — eliminates 100-250 seconds per hour of unnecessary matplotlib rendering on the main thread for a 30-item tracker.
- Fixed matplotlib `Figure` memory leak: each figure was added to matplotlib's global figure registry (`pyplot.get_fignums()`) but never removed when a card was deleted. Added `ItemCard.cleanup()` method that calls `plt.close(self._fig)`, called in `remove_card()` before `card.destroy()`.
- Switched `canvas.draw()` → `canvas.draw_idle()` in `update_graph()`. `draw_idle()` schedules rendering asynchronously in the Tkinter event loop instead of blocking immediately — consistent with how hover events already use it.
- Disabled matplotlib antialiasing (`antialiased=False`) on the price line plot. At 80 DPI on a 5-inch card-sized chart, the visual difference is imperceptible, saving 10-20ms per redraw.

### Performance (2026-06-14 — Save Inspector Row Widget Rewrite)
- Replaced `CTkFrame` + `CTkLabel×4` per inventory row with plain `tk.Frame` + `tk.Label×4`. Same root cause as Add Item Dialog: each CTk widget creates an internal `tk.Canvas` (~2ms each), so 200 items × 5 widgets = ~2 second freeze when opening the Inspector window. Plain tk widgets cost ~0.3ms each — estimated 6x speedup. Hover and selection highlight updated to use `bg=` instead of CTk `fg_color=`. Icon images converted from `ctk.CTkImage` to `ImageTk.PhotoImage` for compatibility with plain `tk.Label`. Fallback initial indicator replaced with a plain colored label (no rounded corners — acceptable tradeoff).

### Performance (2026-06-14 — Add Item Dialog Row Widget Rewrite)
- Replaced CTkButton + CTkLabel + CTkFrame per item row with plain `tk.Frame` + `tk.Label` (native Tkinter widgets). Profiling showed each CTkButton creates an internal `tk.Canvas` for rounded-corner rendering, costing ~10ms per item. With 293 items this caused a 3-second list build. Plain `tk.Label` costs ~1.7ms per item — 6x speedup. Total list build time drops from ~3000ms to ~510ms. Hover and selection effects are replicated via `<Enter>`/`<Leave>`/`<Button-1>` event bindings with manual color management.
- Increased `_BATCH_SIZE` from 60 → 100 (safe now that each batch costs ~170ms instead of 600ms).
- Added automated dialog timing test at `tests/perf_dialog_timing.py`.

### Fixed (2026-06-14 — Add Item Dialog Polish)
- Fixed flash/flicker on dialog open: dialog is now hidden (`alpha=0`) immediately after `super().__init__()` and revealed (`alpha=1`) only after `_center_on()` positions it correctly — no more visible jump to wrong position.
- Fixed first-click delay after startup: added background thread in `_on_catalog_cache_loaded()` and `_on_catalog_ready()` to pre-warm `get_seen_catalog()` cache immediately after catalog loads — dialog opens instantly on first click instead of blocking the main thread for 100–250ms.
- Fixed empty list when clicking filter tabs (All / Owned / Listed / Sold out): replaced `pack_forget()` + `pack()` cycle with `grid_remove()` + `grid()` throughout `_apply_search_filter()` and `_add_item_button()`. The `pack` show/hide cycle was unreliable in CTkScrollableFrame's canvas after deferred batch build, causing items to not render even though the counter showed correct numbers. `grid_remove()` hides widgets while preserving their grid configuration; `grid()` without arguments restores them reliably.
- Increased `_BATCH_SIZE` from 30 → 60: deferred loading completes in half the number of event-loop ticks.

### Performance (2026-06-14 — Add Item Dialog Optimization)
- Fixed "Add Item" button lag: dialog now opens instantly — `get_seen_catalog()` result is cached in memory (`_seen_catalog_cache` in `item_catalog.py`) and only re-queried from SQLite when invalidated. Cache is invalidated after savegame sync (`_on_sync_done`), listing metadata update (`_on_listing_update`), or catalog merge (`_merge_seen`).
- Fixed dialog freeze while list populated: replaced synchronous widget loop (500+ items × 3-4 widgets = 1500+ objects before dialog visible) with deferred batch rendering — dialog appears immediately showing "Loading items...", then builds 30 widgets per event loop tick via `after(0, ...)`. Dialog is fully usable while loading.
- Fixed search box lag per keystroke: added 150ms debounce to `_on_search_change` — typing "chain" now triggers 1 filter pass instead of 5. Actual filter logic extracted to `_apply_search_filter()`.

### Performance (2026-06-14 — Performance Optimization)
- Enabled SQLite WAL (Write-Ahead Logging) mode in `init_db()` — concurrent reads and writes no longer block each other; background workers can write price data while the GUI reads snapshots simultaneously.
- Added `PRAGMA synchronous=NORMAL`, `PRAGMA cache_size=-8000` (8 MB), and `PRAGMA temp_store=MEMORY` to reduce fsync overhead and speed up repeated queries.
- Added composite index `idx_price_history_name_id ON price_history(item_name, id DESC)` — `get_last_price()` is now an indexed lookup instead of a full table scan that grows with usage time.
- Replaced 10 individual SQLite connections at startup (N×2 per tracked item) with 2 batch queries: `get_all_price_snapshots()` and the new `get_all_market_history_cache()`.
- Moved `prune_price_history()` from synchronous main-thread execution to a background daemon thread — app now shows cards immediately without waiting for the prune operation.
- Fixed N+1 query in `_on_listing_update`: replaced `get_all_items()` (full table scan returning all items) with the new `get_item_by_name()` (single-row indexed lookup by name).
- Moved `from .item_card import ItemCard` from inside `add_card()` method body to module level — eliminates repeated Python import machinery overhead on every card creation.
- Added `run_optimize()` call in `_on_closing()` — runs `PRAGMA optimize` on shutdown to keep SQLite query planner statistics fresh for the next session.
- Removed redundant `import os` inside `_on_open_save_inspector()` (already imported at module level).
- Fixed latent `NameError` in `database.py`: `get_market_history_cache()` used `log` which was never defined — added `import logging` and `log = logging.getLogger(__name__)` at module level.

### Fixed (2026-06-14 — Production Audit)
- Fixed `notifier.py` logging hardcoded `"Rp"` currency symbol in alert confirmation message — now uses the dynamic `sym` variable that matches the active currency setting.
- Removed dead `tenacity` dependency from `requirements.txt` — retry logic is implemented manually in `SteamMarketAPI._request()` and `tenacity` was never imported anywhere in the codebase.
- Moved `import os` from inside method bodies (`_on_sync_save`, `_on_browse_save`) to `app.py` module level.
- Moved `from datetime import ...`, `from datetime import datetime`, and `from matplotlib.ticker import FuncFormatter` out of `update_graph()` and `_on_hover()` function bodies in `item_card.py` — these were re-executed on every 60-second price cycle.
- Removed duplicate `# ── Savegame sync` section header comment in `app.py`.
- Replaced `logging.FileHandler` with `RotatingFileHandler` in `main.py` (5 MB per file, 3 backups) — previously `data/app.log` would grow without limit over long runtimes.

### Added
- Added `run.bat` startup script at the project root for launching the GUI application with a double-click, running invisibly in the background via `.venv\Scripts\pythonw.exe` and checking for the existence of `.venv` automatically.
- Added Save File Selector & Save Inspector GUI features, including a persistent `save_path` configuration, a header "Browse" button (which prompts to select/confirm the savegame file path and auto-syncs), a header "Inspector" button (which opens the inventory details window from the configured path), a manual "Sync" button (which instantly syncs using the saved path and falls back to a dialog picker only if not set), and a new premium split-layout top-level window showing the combined inventory and stash items with lock status indicators (🔒), rarity name colors, a real-time search filter, a sorting dropdown (by Alphabetical, Highest Price, or Highest Rarity), and a dynamic details card showing high-res item art, price snapshots, lock status, and type description.
- Added `get_all_price_snapshots()` SQLite function to efficiently load price records for list elements in a single query.
- Added local SQLite market history caching (`market_history_cache` table) with a 1-hour TTL to prevent redundant Steam API queries and allow instant rendering of price history graphs upon application startup.

### Changed
- Fixed an issue where the market history cache prevented fetching missing item images by forcing a fresh request to the Steam Community Market if the item's image is not yet cached locally in `image_cache`.
- Fixed missing images and metadata (rarity color, type) for items with zero active listings on the Steam Community Market (such as sold-out items) by dynamically extracting these properties from the React Server Components data block (`window.SSR.renderContext`) on their respective listing pages and saving them to the local SQLite database.
- Fixed range filter buttons ("Week", "Month", "Year", "Lifetime") and graph currency labels being hidden under the Matplotlib canvas by raising them to the top layer (`.lift()`) over the canvas.
- Adjusted the Matplotlib subplot margins (reducing top margin to `top=0.76`) and fixed the hover tooltip position horizontally on the left/right of the cursor while keeping it vertically centered (`va='center'`) inside the plot area using `xycoords=('data', 'axes fraction')` to completely avoid overlapping with range filter buttons at the top or clipping at the canvas edges at the bottom.
- Synchronized graph axes, hover points, and interactive tooltips to dynamically scale history prices based on the active selected currency, adding a clean USD (`$`) fallback when the local price is not yet loaded.
- Dynamically format tooltip hover prices depending on active currency type (showing no decimals for integer currencies like `Rp`, `₩`, `₫`, `¥`, and two decimals for others).
- Cleaned up linter warnings by removing unused `_HEADERS` import from `src/item_catalog.py` and `Optional` type import from `src/item_mapping.py`.
- Enriched the *Master State* and *Features Specifications* based on comparative analysis of 5 reference repositories. Key design adjustments: sync scheduling of charts with hour transitions, slicing historical data to ±300 points, fetching listing images, status-code classified error handling (429/5xx/4xx) with maximum 5 retries, overlap guard cycles, GUI-based item management (persistence + validation + deduplication), Discord webhook notifications resilience, URL encoding adjustments (`quote_plus` + `~`), and optional purchase price tracking.

### Added
- Added `extract_save.py` script to extract and decrypt local savegame files (`SaveFile_Live.es3`) to user-readable `decrypted_save.json`.
- Completed Phase 4 (GUI Base): Developed `src/gui/app.py` and `main.py` using `CustomTkinter`. Created `MainWindow(ctk.CTk)` dark mode, responsive 3-row layout (fixed header/scroll/fixed footer), header status labels, "+ Add Item" trigger, empty state placeholder, dynamic `update_footer_time()`, and `_on_closing()` handler with stop signals and 3s join timeout. Verified clean start and window close.
- Completed Phase 3 (Daemon Workers): Developed `src/worker.py` containing `_BaseWorker` (daemon thread with interruptible sleep in 1s chunks), `PriceWorker` (single cycle per run, overlap guard via `is_alive()`), and `ListingWorker` (`fetch_colors` flag to separate startup vs hourly checks). Verified callbacks and interruption signals.
- Completed Phase 1 (Steam Client API): Developed `src/steam_api.py` utilizing `requests.Session`, `_encode_name` (`quote_plus` + `~` -> `%7E`), status-code classification with max 5 retries, 3-tier exponential backoff delay, `get_price` (IDR parse + SOLD_OUT state), `get_rarity_color`, and `get_listing_data` (regex parsing + 300-point slice).
- Completed Phase 2 (Local Database): Developed `src/database.py` with `init_db` schemas, `tracked_items` and `price_history` tables, and CRUD handlers (`add_item`, `remove_item`, `get_all_items`, `get_item_count`, `update_item_metadata`, `update_alert_price`, `save_price`, `get_last_price`).
- Completed Phase 0 (Environment Setup): Standard folder structure `src/`, `src/gui/`, `assets/`; virtual environment setup (`.venv`); dependencies configured (`customtkinter 5.2.2`, `requests 2.34.2`, `tenacity 9.1.4`, `matplotlib 3.10.9`, `Pillow 12.2.0`, `python-dotenv 1.2.2`); and `requirements.txt` locked.
- Initial project structure, core docs, and `.gitignore`.
