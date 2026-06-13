# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Changed
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
