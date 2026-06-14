import logging
import os
import time
import threading
import urllib.request
import customtkinter as ctk
from datetime import datetime

from ..database import (
    get_all_items, get_item_by_name, add_item, remove_item,
    save_price, get_last_price, update_item_metadata, get_alert_price,
    clear_price_history, clear_price_snapshots, prune_price_history,
    replace_owned_items, get_all_seen_items, upsert_seen_items,
    upsert_snapshot_ask, upsert_snapshot_buy, get_all_price_snapshots,
    get_cached_image, save_cached_image, get_uncached_item_images,
    get_all_market_history_cache, run_optimize,
)
from ..worker import PriceWorker, ListingWorker, seconds_until_next_hour
from ..notifier import send_alert
from .. import config as _cfg
from .. import item_catalog
from .. import save_reader
from .. import item_mapping
from .item_card import ItemCard

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

log = logging.getLogger(__name__)

VERSION = "0.1.0"
CYCLE_INTERVAL_MS = 60_000   # price cycle interval: 60 seconds


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("TBH Market Tracker")
        self.geometry("960x620")
        self.minsize(720, 460)

        self._stop_event = threading.Event()
        self._price_worker = None
        self._listing_worker = None
        self._prewarm_thread = None
        self._cards: dict = {}

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.after(200, self._startup)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_scroll_area()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color=("gray85", "gray17"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="TBH Market Tracker",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=20, sticky="w")

        self._status_label = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="gray55",
        )
        self._status_label.grid(row=0, column=1, padx=8)

        currency_labels = [f"{name} ({sym})" for _, name, sym in _cfg.STEAM_CURRENCIES]
        self._currency_menu = ctk.CTkOptionMenu(
            header,
            values=currency_labels,
            command=self._on_currency_change,
            width=130,
            font=ctk.CTkFont(size=12),
        )
        self._currency_menu.set(_cfg.get_currency_label())
        self._currency_menu.grid(row=0, column=2, padx=(0, 8), pady=10)

        self._btn_sync_save = ctk.CTkButton(
            header,
            text="⇄ Sync",
            width=70,
            fg_color="transparent",
            border_width=1,
            border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"),
            hover_color=("gray75", "gray28"),
            font=ctk.CTkFont(size=12),
            command=self._on_sync_save,
        )
        self._btn_sync_save.grid(row=0, column=3, padx=(0, 6), pady=10)

        self._btn_export_save = ctk.CTkButton(
            header,
            text="📥 Export",
            width=75,
            fg_color="transparent",
            border_width=1,
            border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"),
            hover_color=("gray75", "gray28"),
            font=ctk.CTkFont(size=12),
            command=self._on_export_save,
        )
        self._btn_export_save.grid(row=0, column=4, padx=(0, 6), pady=10)

        self._btn_browse_save = ctk.CTkButton(
            header,
            text="📁 Browse",
            width=80,
            fg_color="transparent",
            border_width=1,
            border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"),
            hover_color=("gray75", "gray28"),
            font=ctk.CTkFont(size=12),
            command=self._on_browse_save,
        )
        self._btn_browse_save.grid(row=0, column=5, padx=(0, 6), pady=10)

        self._btn_save_inspector = ctk.CTkButton(
            header,
            text="🔍 Inspector",
            width=85,
            fg_color="transparent",
            border_width=1,
            border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"),
            hover_color=("gray75", "gray28"),
            font=ctk.CTkFont(size=12),
            command=self._on_open_save_inspector,
        )
        self._btn_save_inspector.grid(row=0, column=6, padx=(0, 6), pady=10)

        self._btn_refresh_catalog = ctk.CTkButton(
            header,
            text="↻ Catalog",
            width=85,
            fg_color="transparent",
            border_width=1,
            border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"),
            hover_color=("gray75", "gray28"),
            font=ctk.CTkFont(size=12),
            command=self._on_refresh_catalog,
        )
        self._btn_refresh_catalog.grid(row=0, column=7, padx=(0, 6), pady=10)

        self._btn_add = ctk.CTkButton(
            header,
            text="+ Add Item",
            width=100,
            command=self._on_add_item,
        )
        self._btn_add.grid(row=0, column=8, padx=(0, 20), pady=10, sticky="e")


    def _build_scroll_area(self):
        self._scroll = ctk.CTkScrollableFrame(
            self, corner_radius=0, fg_color="transparent"
        )
        self._scroll.grid(row=1, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)
        self._scroll.grid_columnconfigure(1, weight=1)

        self._empty_label = ctk.CTkLabel(
            self._scroll,
            text='No items tracked yet.\nClick  "+ Add Item"  to get started.',
            font=ctk.CTkFont(size=13),
            text_color="gray50",
        )
        self._empty_label.grid(row=0, column=0, columnspan=2, pady=100)

    def _build_footer(self):
        footer = ctk.CTkFrame(self, height=30, corner_radius=0, fg_color=("gray80", "gray13"))
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_propagate(False)
        footer.grid_columnconfigure(0, weight=1)

        self._footer_label = ctk.CTkLabel(
            footer,
            text=f"v{VERSION}",
            font=ctk.CTkFont(size=11),
            text_color="gray45",
        )
        self._footer_label.grid(row=0, column=0, padx=16, sticky="w")

    # ── Startup ───────────────────────────────────────────────────────────────

    def _startup(self):
        """
        Load persisted items from DB → create cards → start price cycle.
        Catalog is loaded from local cache only (zero network).
        User can force a fresh catalog fetch via '↻ Catalog' button.
        """
        # Prune old rows in background — no need to block UI for this
        threading.Thread(
            target=lambda: log.info("Pruned %d price history rows.", prune_price_history(90)),
            daemon=True,
        ).start()

        # Load catalog from local JSON cache (no network request)
        threading.Thread(target=self._load_catalog_cache_bg, daemon=True).start()

        items = get_all_items()
        if not items:
            self.set_status("No items tracked. Click '+ Add Item' to start.")
            return

        # Batch-load all snapshots and history in 2 queries instead of N*2 connections
        all_snapshots = get_all_price_snapshots()
        all_histories = get_all_market_history_cache()

        for item in items:
            self.add_card(item["name"], color_hex=item["color_hex"])
            card = self.get_card(item["name"])
            if card:
                if item.get("item_type"):
                    card.set_item_type(item["item_type"])
                # Load image from stored URL (no extra Steam request)
                if item.get("image_url"):
                    self._fetch_image_async(card, item["name"], item["image_url"])
                # Restore last known prices (zero network — from local DB snapshot)
                snap = all_snapshots.get(item["name"])
                if snap:
                    if snap["ask"] is not None:
                        card.update_price({"status": "OK", "price": snap["ask"],
                                           "median_price": None, "volume": None})
                    if snap["buy_highest"] is not None or snap["buy_count"]:
                        card.update_buy_orders({"highest_price": snap["buy_highest"],
                                                "count": snap["buy_count"] or 0})
                # Restore cached history graph if available (zero network)
                cached_hist = all_histories.get(item["name"])
                if cached_hist:
                    card.update_graph(cached_hist["history"])

        self._run_price_cycle()
        # First orderbook fetch ~50s after startup (after the first price cycle),
        # then hourly. Buy orders work again via the new orderbook endpoint.
        self.after(50_000, lambda: self._start_listing_worker(list(self._cards.keys())))
        self._schedule_hourly_listing()

    def _load_catalog_cache_bg(self):
        """Background: load catalog from local cache only, then update cards."""
        catalog = item_catalog.load_cache_only()
        self.after(0, lambda: self._on_catalog_cache_loaded(catalog))

    def _on_catalog_cache_loaded(self, catalog: list):
        """Apply cached catalog metadata to cards (color/type/icon from catalog, if better than DB)."""
        updated = 0
        for name, card in self._cards.items():
            cat = item_catalog.get_item(name)
            if not cat:
                continue
            card.set_rarity_color(cat.color_hex)
            card.set_item_type(cat.item_type)
            update_item_metadata(name, cat.color_hex, cat.item_type, cat.icon_url, None)
            if cat.icon_url:
                self._fetch_image_async(card, name, cat.icon_url)
            updated += 1
        if catalog:
            age = item_catalog.cache_age_str()
            self.set_status(f"Catalog cache — {len(catalog)} items ({age}).")
            self.after(3000, lambda: self.set_status(""))
        else:
            # No local cache — auto-fetch from Steam in the background
            log.info("No catalog cache — scheduling auto-fetch.")
            self.after(3_000, self._on_refresh_catalog)
        log.info("Catalog cache applied to %d cards.", updated)
        self._start_image_prewarm()
        threading.Thread(target=item_catalog.get_seen_catalog, daemon=True).start()

    def _fetch_catalog_bg(self, force: bool):
        """Background thread: fetch catalog from Steam, then dispatch to main thread."""
        catalog = item_catalog.get_or_fetch_catalog(force=force)
        self.after(0, lambda: self._on_catalog_ready(catalog, force))

    def _on_catalog_ready(self, catalog: list, force: bool):
        """Update all tracked cards with color/type/icon from the catalog."""
        for name, card in self._cards.items():
            cat = item_catalog.get_item(name)
            if not cat:
                continue
            card.set_rarity_color(cat.color_hex)
            card.set_item_type(cat.item_type)
            update_item_metadata(name, cat.color_hex, cat.item_type, cat.icon_url, None)
            if cat.icon_url:
                self._fetch_image_async(card, name, cat.icon_url)

        source = "updated" if force else "cache"
        self.set_status(f"Catalog {source} — {len(catalog)} items.")
        self.after(3000, lambda: self.set_status(""))
        self._set_catalog_loading(False)
        log.info("Catalog applied to %d tracked cards (force=%s).", len(self._cards), force)
        self._start_image_prewarm()
        threading.Thread(target=item_catalog.get_seen_catalog, daemon=True).start()

    def _set_catalog_loading(self, loading: bool):
        """Toggle refresh button state while catalog is being fetched."""
        if loading:
            self._btn_refresh_catalog.configure(text="...", state="disabled")
        else:
            self._btn_refresh_catalog.configure(text="↻ Catalog", state="normal")

    def _on_refresh_catalog(self):
        """Manual refresh: force-fetch catalog regardless of cache age."""
        self._set_catalog_loading(True)
        self.set_status("Fetching latest catalog from Steam...")
        threading.Thread(target=self._fetch_catalog_bg, args=(True,), daemon=True).start()

    # ── Savegame sync & Inspector ─────────────────────────────────────────────

    def _on_sync_save(self):
        """Manual sync: read from the saved path. If not set, prompt to select."""
        from tkinter import filedialog

        path = _cfg.get_save_path()
        if not path or not os.path.exists(path):
            # Fallback to file dialog
            initial_dir = None
            if path:
                initial_dir = os.path.dirname(path)
            else:
                default_dir = os.path.dirname(save_reader.SAVE_PATH)
                if os.path.exists(default_dir):
                    initial_dir = default_dir

            path = filedialog.askopenfilename(
                title="Select Task Bar Hero Save File to Sync",
                initialdir=initial_dir,
                filetypes=[("Easy Save 3 Files", "*.es3;*.bak"), ("All Files", "*.*")]
            )
            if not path:
                return  # User cancelled
            _cfg.set_save_path(path)

        self._btn_sync_save.configure(text="...", state="disabled")
        self.set_status("Reading savegame...")
        threading.Thread(target=self._sync_save_bg, args=(path,), daemon=True).start()

    def _sync_save_bg(self, path):
        """
        Background: decrypt local save (read-only, no network to Steam),
        map ItemKeys → market hash names, store result in items_owned.
        Also seeds sold-out owned items into items_seen so they appear in
        the Add Item dialog even if they have no active Steam Market listings.
        """
        try:
            owned_counts = save_reader.get_owned_counts(path)
            # key_to_market_names works without items_seen — discovers sold-out items too
            owned = item_mapping.key_to_market_names(owned_counts)
            replace_owned_items(owned)

            # Seed owned items missing from items_seen as sold-out entries
            seen_names = {r["hash_name"] for r in get_all_seen_items()}
            new_seen = [
                {"hash_name": name, "item_type": "", "color_hex": "FFFFFF", "icon_url": None}
                for name in owned
                if name not in seen_names
            ]
            if new_seen:
                upsert_seen_items(new_seen)
                log.info("Seeded %d owned-but-unlisted items into items_seen.", len(new_seen))

            total = sum(owned.values())
            msg = f"Save synced — {len(owned)} tradable items owned ({total} total)."
            log.info(msg)
        except save_reader.SaveReadError as exc:
            msg = f"Sync failed: {exc}"
            log.warning(msg)
        except Exception as exc:
            msg = f"Sync failed: {exc}"
            log.exception("Savegame sync failed.")
        self.after(0, lambda: self._on_sync_done(msg))

    def _on_sync_done(self, msg: str):
        item_catalog.invalidate_seen_catalog_cache()
        self._btn_sync_save.configure(text="⇄ Sync", state="normal")
        self.set_status(msg)
        self.after(5000, lambda: self.set_status(""))

    def _on_browse_save(self):
        """Browse: prompt to select save file path, store it, and trigger sync."""
        from tkinter import filedialog

        saved_path = _cfg.get_save_path()
        initial_dir = None
        if saved_path:
            initial_dir = os.path.dirname(saved_path)
        else:
            default_dir = os.path.dirname(save_reader.SAVE_PATH)
            if os.path.exists(default_dir):
                initial_dir = default_dir

        path = filedialog.askopenfilename(
            title="Select Task Bar Hero Save File",
            initialdir=initial_dir,
            filetypes=[("Easy Save 3 Files", "*.es3;*.bak"), ("All Files", "*.*")]
        )
        if not path:
            return  # User cancelled

        _cfg.set_save_path(path)
        self.set_status("Save path updated.")
        self._btn_sync_save.configure(text="...", state="disabled")
        threading.Thread(target=self._sync_save_bg, args=(path,), daemon=True).start()

    def _on_export_save(self):
        """Decrypt the selected save file and export it as formatted JSON."""
        from tkinter import filedialog, messagebox
        import json

        path = _cfg.get_save_path()
        if not path or not os.path.exists(path):
            messagebox.showwarning(
                "Warning",
                "Save game location has not been selected. Please click the 'Browse' button first."
            )
            return

        initial_name = "decrypted_save.json"
        dest_path = filedialog.asksaveasfilename(
            title="Export Decrypted Save As JSON",
            initialfile=initial_name,
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if not dest_path:
            return

        try:
            data = save_reader.decrypt_save(path)
            with open(dest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            messagebox.showinfo(
                "Export Success",
                f"Save game decrypted successfully and exported to:\n{dest_path}"
            )
            self.set_status("Save exported successfully.")
            self.after(4000, lambda: self.set_status(""))
        except Exception as exc:
            log.exception("Export save game failed.")
            messagebox.showerror(
                "Export Failed",
                f"An error occurred while decrypting/saving: {exc}"
            )

    def _on_open_save_inspector(self):
        """Open the Save Inspector window using the saved path. Shows a warning if not set."""
        from tkinter import messagebox
        from .save_inspector import SaveInspectorWindow

        path = _cfg.get_save_path()
        if not path or not os.path.exists(path):
            messagebox.showwarning(
                "Warning",
                "Save game location has not been selected. Please click the 'Browse' button first."
            )
            return

        self._save_inspector_window = SaveInspectorWindow(self, path)


    # ── Price cycle ───────────────────────────────────────────────────────────

    def _run_price_cycle(self):
        """Start one PriceWorker cycle, then reschedule after CYCLE_INTERVAL_MS."""
        if self._stop_event.is_set():
            return

        names = list(self._cards.keys())
        if not names:
            self.after(CYCLE_INTERVAL_MS, self._run_price_cycle)
            return

        if self._price_worker and self._price_worker.is_alive():
            log.warning("Price cycle overlap — skipping this cycle.")
            self.after(CYCLE_INTERVAL_MS, self._run_price_cycle)
            return

        if item_catalog.is_fetching():
            log.info("Catalog fetch in progress — skipping price cycle to avoid rate limit.")
            self.after(CYCLE_INTERVAL_MS, self._run_price_cycle)
            return

        if self._listing_worker and self._listing_worker.is_alive():
            log.info("ListingWorker in progress — skipping price cycle to avoid rate limit.")
            self.after(CYCLE_INTERVAL_MS, self._run_price_cycle)
            return

        self.set_status("Fetching prices...")
        self._price_worker = PriceWorker(names, self._on_price_update, self._stop_event)
        self._price_worker.start()
        self._poll_price_done()
        self.after(CYCLE_INTERVAL_MS, self._run_price_cycle)

    def _poll_price_done(self):
        if self._price_worker and self._price_worker.is_alive():
            self.after(1000, self._poll_price_done)
        else:
            self.set_status("")

    def _on_price_update(self, name: str, result: dict):
        def _update():
            card = self.get_card(name)
            if card is None:
                return

            last_price = get_last_price(name)
            card.update_price(result, last_price)

            if result.get("status") == "OK":
                current = result["price"]
                save_price(name, current)
                upsert_snapshot_ask(name, current)
                self._check_alert(name, current, last_price)

            self.update_footer_time()

        self.after(0, _update)

    def _check_alert(self, name: str, current: float, last_price):
        threshold = get_alert_price(name)
        if threshold is None:
            return
        crossed_below = current <= threshold and (last_price is None or last_price > threshold)
        if crossed_below:
            threading.Thread(
                target=send_alert,
                args=(name, current, threshold),
                daemon=True,
            ).start()

    # ── Listing / hourly refresh ──────────────────────────────────────────────

    def _start_listing_worker(self, names: list):
        if self._listing_worker and self._listing_worker.is_alive():
            log.warning("ListingWorker already running — skipping.")
            return
        self._listing_worker = ListingWorker(
            names, self._on_listing_update, self._stop_event,
        )
        self._listing_worker.start()

    def _schedule_hourly_listing(self):
        delay_ms = int(seconds_until_next_hour() * 1000)
        self.after(delay_ms, self._run_hourly_listing)

    def _run_hourly_listing(self):
        if self._stop_event.is_set():
            return
        names = list(self._cards.keys())
        if names:
            self._start_listing_worker(names)
        self._schedule_hourly_listing()

    def _on_listing_update(
        self, name, history, image_url, buy_orders, color_hex, item_type, item_nameid
    ):
        """ListingWorker callback — metadata fields may be provided if listing was parsed."""
        def _update():
            card = self.get_card(name)
            if card is None:
                return

            card.update_graph(history)

            # Update metadata if extracted from listing page
            if color_hex:
                card.set_rarity_color(color_hex)
            if item_type:
                card.set_item_type(item_type)
            if image_url:
                self._fetch_image_async(card, name, image_url)

            if color_hex or item_type or image_url:
                item_db = get_item_by_name(name)
                db_color = color_hex or (item_db["color_hex"] if item_db else "FFFFFF")
                db_type = item_type or (item_db["item_type"] if item_db else "")
                db_image = image_url or (item_db["image_url"] if item_db else None)
                update_item_metadata(name, db_color, db_type, db_image, None)
                upsert_seen_items([{
                    "hash_name": name,
                    "item_type": db_type,
                    "color_hex": db_color,
                    "icon_url": db_image
                }])
                item_catalog.invalidate_seen_catalog_cache()

            # Orderbook currency follows Steam geo-IP, not our setting —
            # only display when it matches the selected currency.
            ob_currency = buy_orders.get("currency")
            try:
                selected = int(_cfg.get_currency_code())
            except (ValueError, TypeError):
                selected = None
            if ob_currency is None or selected is None or ob_currency == selected:
                card.update_buy_orders(buy_orders)
                upsert_snapshot_buy(
                    name,
                    buy_orders.get("highest_price"),
                    buy_orders.get("count", 0),
                )
            else:
                log.warning(
                    "Orderbook currency %s != selected %s for %s — buy order hidden.",
                    ob_currency, selected, name,
                )

        self.after(0, _update)

    def _fetch_image_async(self, card, item_name: str, url: str):
        def _fetch():
            try:
                # Serve from local DB cache first — item art is static, never expires
                cached = get_cached_image(item_name)
                if cached:
                    log.debug("Image cache hit: %s (%d bytes)", item_name, len(cached))
                    if self.get_card(item_name):
                        self.after(0, lambda: card.set_image(cached))
                    return

                # Cache miss — download then persist for all future startups
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                save_cached_image(item_name, data)
                log.debug("Image cached: %s (%d bytes)", item_name, len(data))
                if self.get_card(item_name):
                    self.after(0, lambda: card.set_image(data))
            except Exception as exc:
                log.warning("Image fetch failed for %s: %s", item_name, exc)

        threading.Thread(target=_fetch, daemon=True).start()

    def _start_image_prewarm(self):
        """Background-download images for every seen item not yet in image_cache.
        Runs after catalog is loaded so icon_urls are available. Safe to call
        multiple times — skips if a pre-warm is already in progress."""
        if self._prewarm_thread and self._prewarm_thread.is_alive():
            return
        self._prewarm_thread = threading.Thread(target=self._prewarm_images_bg, daemon=True)
        self._prewarm_thread.start()

    def _prewarm_images_bg(self):
        """
        Download images for all catalog items missing from image_cache.
        Uses Steam's Fastly CDN — separate from the market API, no rate-limit risk.
        0.3 s delay between requests is conservative for a static-asset CDN.
        Tracked-item images are already fetched by _fetch_image_async; this covers
        the rest so they load instantly when the user adds them later.
        """
        pending = get_uncached_item_images()
        if not pending:
            log.debug("Image pre-warm: nothing to download, all items already cached.")
            return

        log.info("Image pre-warm: %d item images to cache.", len(pending))
        ok = 0
        for i, item in enumerate(pending):
            if self._stop_event.is_set():
                break
            name = item["hash_name"]
            url  = item["icon_url"]
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                save_cached_image(name, data)
                ok += 1

                # Apply immediately if this item happens to be tracked
                card = self.get_card(name)
                if card:
                    self.after(0, lambda c=card, d=data: c.set_image(d))

            except Exception as exc:
                log.debug("Pre-warm skip %s: %s", name, exc)

            if i < len(pending) - 1 and not self._stop_event.is_set():
                time.sleep(0.3)   # CDN-safe delay — Fastly, not Steam API

        log.info("Image pre-warm done: %d/%d cached.", ok, len(pending))

    # ── Card management ───────────────────────────────────────────────────────

    def add_card(self, item_name: str, color_hex: str = "FFFFFF"):
        if item_name in self._cards:
            return
        self._empty_label.grid_remove()
        card = ItemCard(self._scroll, item_name, color_hex, on_delete=self._on_delete_item)
        self._cards[item_name] = card
        self._re_grid_cards()

    def remove_card(self, item_name: str):
        card = self._cards.pop(item_name, None)
        if card:
            card.cleanup()
            card.destroy()
        if not self._cards:
            self._empty_label.grid()
        else:
            self._re_grid_cards()

    def get_card(self, item_name: str):
        return self._cards.get(item_name)

    def _re_grid_cards(self):
        names = list(self._cards.keys())
        for i, name in enumerate(names):
            card = self._cards[name]
            row, col = divmod(i, 2)
            alone_in_row = (i == len(names) - 1) and (col == 0)
            if alone_in_row:
                card.grid(row=row, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")
            else:
                padx = (8, 4) if col == 0 else (4, 8)
                card.grid(row=row, column=col, columnspan=1, padx=padx, pady=(0, 8), sticky="ew")

    # ── Status helpers ────────────────────────────────────────────────────────

    def set_status(self, text: str):
        self._status_label.configure(text=text)

    def update_footer_time(self):
        now = datetime.now().strftime("%H:%M")
        self._footer_label.configure(text=f"v{VERSION}   ·   Last updated: {now}")

    # ── Dialog / item callbacks ───────────────────────────────────────────────

    def _on_add_item(self):
        from .add_dialog import AddItemDialog
        AddItemDialog(
            self,
            current_names=list(self._cards.keys()),
            on_confirm=self._handle_new_item,
            catalog=item_catalog.get_seen_catalog(),
        )

    def _handle_new_item(self, name: str):
        if not add_item(name):
            return  # already in DB — defensive, dialog already validates dedup
        self.add_card(name)

        # Apply catalog metadata immediately (catalog is usually ready by the time user adds)
        cat = item_catalog.get_item(name)
        if cat:
            card = self.get_card(name)
            if card:
                card.set_rarity_color(cat.color_hex)
                card.set_item_type(cat.item_type)
                update_item_metadata(name, cat.color_hex, cat.item_type, None, None)
                if cat.icon_url:
                    self._fetch_image_async(card, name, cat.icon_url)

        self._start_listing_worker([name])

    def _on_delete_item(self, item_name: str):
        remove_item(item_name)
        self.remove_card(item_name)

    # ── Currency ──────────────────────────────────────────────────────────────

    def _on_currency_change(self, choice: str):
        code = _cfg.LABEL_TO_CODE.get(choice)
        if not code:
            return
        _cfg.set_currency(code)
        symbol = _cfg.get_currency_symbol()

        for card in self._cards.values():
            card.set_currency_symbol(symbol)

        clear_price_history()
        clear_price_snapshots()
        log.info("Currency changed to %s. Price history and snapshots cleared.", choice)
        self.after(0, self._run_price_cycle)

    # ── Closing ───────────────────────────────────────────────────────────────

    def _on_closing(self):
        self._stop_event.set()
        for worker in (self._price_worker, self._listing_worker, self._prewarm_thread):
            if worker and worker.is_alive():
                worker.join(timeout=3)
        run_optimize()
        self.destroy()
