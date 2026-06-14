import os
import io
import logging
import tkinter as tk
import threading
import urllib.request
from typing import Dict, List, Optional
import customtkinter as ctk
from PIL import Image, ImageTk

from .. import save_reader
from ..database import get_cached_image, get_all_price_snapshots, save_cached_image, get_all_seen_items
from ..item_mapping import get_game_items, _english_name
from .. import config as _cfg
from .. import item_catalog

log = logging.getLogger(__name__)

GRADE_COLORS = {
    "COMMON": "#B5B5B5",
    "UNCOMMON": "#7CE937",
    "RARE": "#519FFF",
    "LEGENDARY": "#EBBB00",
    "IMMORTAL": "#E8695A",
    "ARCANA": "#FB86FF",
    "BEYOND": "#FF9900",
    "CELESTIAL": "#00F6FF",
    "DIVINE": "#FFFFFF",
    "COSMIC": "#FFD700"
}

# Rarity sort order weights
RARITY_WEIGHTS = {
    "COSMIC": 10,
    "DIVINE": 9,
    "CELESTIAL": 8,
    "BEYOND": 7,
    "ARCANA": 6,
    "IMMORTAL": 5,
    "LEGENDARY": 4,
    "RARE": 3,
    "UNCOMMON": 2,
    "COMMON": 1
}

import re
_GEAR_NAME_RE = re.compile(
    r"^(?P<name>.+?) "
    r"\((?P<grade>Common|Uncommon|Rare|Legendary|Immortal|Arcana|Beyond|Celestial|Divine|Cosmic)\) "
    r"(?P<var>[AB])$"
)



def normalize_key(key: int) -> int:
    if isinstance(key, int) and key >= 100_000_000:
        return key // 1000
    return key


class SaveInspectorWindow(ctk.CTkToplevel):
    """Special window to inspect inventory and stash items from the save game file."""

    def __init__(self, parent, save_path: str):
        super().__init__(parent)
        self.title("Save Inspector")
        self.geometry("920x600")
        self.minsize(860, 500)

        # Make window modal-like
        self.transient(parent)
        self.grab_set()
        self.focus_set()

        self._save_path = save_path
        self._items_db: Dict[int, dict] = {}
        self._save_data: dict = {}
        self._price_snapshots: Dict[str, dict] = {}

        # List of item data dicts
        self._items_list: List[dict] = []
        
        # Selected item tracking
        self._selected_row_frame = None

        # Row colors (plain tk widgets don't inherit CTk theming)
        _c = {"row": "#2d2d2d", "hover": "#3a3a3a", "sel": "#525252"} \
             if ctk.get_appearance_mode() == "Dark" \
             else {"row": "#d8d8d8", "hover": "#c3c3c3", "sel": "#a6a6a6"}
        self._row_bg    = _c["row"]
        self._row_hover = _c["hover"]
        self._row_sel   = _c["sel"]

        # Load tbh_items catalog
        try:
            game_items = get_game_items()
            self._items_db = {it["id"]: it for it in game_items if it.get("id")}
        except Exception as e:
            log.warning("Failed to load tbh_items catalog: %s", e)

        # Load local price snapshots
        try:
            self._price_snapshots = get_all_price_snapshots()
        except Exception as e:
            log.warning("Failed to load price snapshots: %s", e)

        # Decrypt save file
        try:
            self._save_data = save_reader.decrypt_save(save_path)
            self._parse_save_items()
            self._build_ui()
        except Exception as exc:
            log.exception("Save decryption failed during inspect.")
            self._build_error_ui(str(exc))

        self._center_on(parent)

    def _build_error_ui(self, error_msg: str):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        err_frame = ctk.CTkFrame(self, fg_color="transparent")
        err_frame.grid(row=0, column=0, padx=20, pady=20)

        ctk.CTkLabel(
            err_frame,
            text="⚠️ Decryption Failed",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#E8695A"
        ).pack(pady=10)

        ctk.CTkLabel(
            err_frame,
            text=f"Error: {error_msg}\n\nMake sure you select a valid SaveFile_Live.es3 file.",
            font=ctk.CTkFont(size=12),
            text_color="gray75",
            wraplength=480,
            justify="center"
        ).pack(pady=10)

        ctk.CTkButton(
            err_frame,
            text="Close",
            width=120,
            command=self.destroy
        ).pack(pady=15)

    def _parse_save_items(self):
        """Parse all items from Inventory, Stash, and Trade Stash, matching them with local metadata and prices."""
        locations = [
            ("inventorySaveDatas", "Inventory"),
            ("stashSaveDatas", "Stash"),
            ("tradingStashSaveDatas", "Trade Stash")
        ]

        # Group IDs by (english_name, GRADE) to detect A/B gear pairs
        by_name_grade = {}
        for it_key, it in self._items_db.items():
            n = _english_name(it)
            grade = (it.get("grade") or "").upper()
            if n and grade:
                by_name_grade.setdefault((n, grade), []).append(it_key)
        for ids in by_name_grade.values():
            ids.sort()

        # Build seen icon lookup
        seen_icons = {}
        try:
            seen_items = get_all_seen_items()
            for s in seen_items:
                if s.get("icon_url"):
                    seen_icons[s["hash_name"]] = s["icon_url"]
        except Exception:
            pass

        # Build base name image & icon lookup for fallbacks (cross-grade)
        base_name_images = {}
        base_name_icons = {}
        try:
            from ..database import _DB_PATH
            import sqlite3
            with sqlite3.connect(_DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT hash_name, image_data FROM image_cache").fetchall()
                for r in rows:
                    hname = r["hash_name"]
                    match = _GEAR_NAME_RE.match(hname)
                    base_n = match.group("name") if match else hname
                    base_name_images[base_n] = bytes(r["image_data"])
        except Exception:
            pass

        # Similarly map base name to icon url from seen_icons
        for hname, url in seen_icons.items():
            if url:
                match = _GEAR_NAME_RE.match(hname)
                base_n = match.group("name") if match else hname
                base_name_icons[base_n] = url

        # Also populate from in-memory catalog
        try:
            for cat_item in item_catalog.get_catalog():
                if cat_item.icon_url:
                    match = _GEAR_NAME_RE.match(cat_item.hash_name)
                    base_n = match.group("name") if match else cat_item.hash_name
                    base_name_icons[base_n] = cat_item.icon_url
        except Exception:
            pass

        raw_items = self._save_data.get("itemSaveDatas", [])
        items_by_uid = {it.get("UniqueId"): it for it in raw_items if it.get("UniqueId")}

        for key, loc_name in locations:
            slots = self._save_data.get(key, [])
            for slot in slots:
                # Inventory slots can have structure like {"ItemUniqueId": 525378783772615569}
                uid = (slot.get("ItemUniqueId") or slot.get("UniqueId")) if isinstance(slot, dict) else slot
                if not uid or uid not in items_by_uid:
                    continue
                item_inst = items_by_uid[uid]
                item_key = normalize_key(item_inst.get("ItemKey"))
                item_meta = self._items_db.get(item_key)

                if not item_meta:
                    continue

                n = _english_name(item_meta)
                raw_grade = (item_meta.get("grade") or "").upper()
                peer_ids = by_name_grade.get((n, raw_grade), [])

                if len(peer_ids) >= 2:
                    # Gear with A/B variants — lower ID = A, higher = B
                    if item_key in peer_ids:
                        grade_cap = raw_grade[0] + raw_grade[1:].lower()  # "ARCANA" → "Arcana"
                        var = "A" if peer_ids.index(item_key) == 0 else "B"
                        item_name = f"{n} ({grade_cap}) {var}"
                    else:
                        item_name = n
                else:
                    item_name = n

                item_type = item_meta.get("type", "UNKNOWN")
                item_grade = item_meta.get("grade", "COMMON")
                is_blocked = item_inst.get("IsBlocked", False)

                # Fetch price details
                price_snap = self._price_snapshots.get(item_name, {})
                ask_price = price_snap.get("ask")
                buy_price = price_snap.get("buy_highest")

                # Try to load cached image bytes
                img_data = get_cached_image(item_name)
                
                # Cross-grade image fallback (borrowing image from other grades)
                base_name = n
                if not img_data:
                    img_data = base_name_images.get(base_name)

                icon_url = None
                if not img_data:
                    icon_url = seen_icons.get(item_name)
                    if not icon_url:
                        cat_item = item_catalog.get_item(item_name)
                        if cat_item:
                            icon_url = cat_item.icon_url
                    # Cross-grade icon url fallback
                    if not icon_url:
                        icon_url = base_name_icons.get(base_name)

                self._items_list.append({
                    "uid": uid,
                    "name": item_name,
                    "type": item_type,
                    "grade": item_grade,
                    "location": loc_name,
                    "is_blocked": is_blocked,
                    "ask_price": ask_price,
                    "buy_price": buy_price,
                    "img_data": img_data,
                    "icon_url": icon_url,
                    "row_frame": None # Will be linked in UI creation
                })

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=3) # Left: List panel
        self.grid_columnconfigure(1, weight=2) # Right: Detail panel

        # ── LEFT PANEL: LIST, SEARCH, SORT ─────────────────────────────────────
        left_panel = ctk.CTkFrame(self, fg_color="transparent")
        left_panel.grid(row=0, column=0, padx=(16, 8), pady=16, sticky="nsew")
        left_panel.grid_rowconfigure(1, weight=1)
        left_panel.grid_columnconfigure(0, weight=1)

        # Header controls frame (Search + Sort)
        ctrl_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        ctrl_frame.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        ctrl_frame.grid_columnconfigure(0, weight=3)
        ctrl_frame.grid_columnconfigure(1, weight=2)

        # Search Bar
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", self._on_filter_changed)
        search_entry = ctk.CTkEntry(
            ctrl_frame,
            textvariable=self._search_var,
            placeholder_text="Search items...",
            height=32,
            font=ctk.CTkFont(size=12)
        )
        search_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        # Sort Dropdown
        self._sort_menu = ctk.CTkOptionMenu(
            ctrl_frame,
            values=[
                "Sort: Alphabetical A-Z",
                "Sort: Alphabetical Z-A",
                "Sort: Highest Price",
                "Sort: Highest Rarity"
            ],
            command=self._on_filter_changed,
            height=32,
            font=ctk.CTkFont(size=12)
        )
        self._sort_menu.grid(row=0, column=1, sticky="ew")

        # Scroll list of items
        self._inv_scroll = ctk.CTkScrollableFrame(left_panel, fg_color=("gray85", "gray18"))
        self._inv_scroll.grid(row=1, column=0, sticky="nsew")
        self._inv_scroll.grid_columnconfigure(0, weight=1)

        # ── RIGHT PANEL: DETAILED SPECIFICATIONS CARD ──────────────────────────
        self._detail_panel = ctk.CTkFrame(self, fg_color=("gray82", "gray14"), corner_radius=12)
        self._detail_panel.grid(row=0, column=1, padx=(8, 16), pady=16, sticky="nsew")
        self._build_detail_panel()

        # Populate inventory rows in scroll view
        self._create_inventory_rows()

        # Display initial placeholder or first item
        if self._items_list:
            # Sort initial list alphabetically A-Z
            self._items_list.sort(key=lambda x: x["name"].lower())
            self._update_scroll_packing()
            self._select_item_row(self._items_list[0])
        else:
            self._show_empty_detail_placeholder()

    def _build_detail_panel(self):
        """Pre-create all widgets in the right detail panel.
        Content is updated via _update_detail_card(); visibility is toggled via
        _show_empty_detail_placeholder(). No widget is ever destroyed at runtime.
        """
        # Centered label shown when no items match the search filter
        self._d_placeholder = ctk.CTkLabel(
            self._detail_panel,
            text="No items found.",
            font=ctk.CTkFont(size=13, slant="italic"),
            text_color="gray55",
        )

        # Large item image container and label
        self._d_img_container = ctk.CTkFrame(self._detail_panel, fg_color="transparent", width=128, height=128)
        self._d_img_container.pack_propagate(False) # Keep container size static
        self._d_img_label = None

        # Item name rendered in rarity color
        self._d_name_label = ctk.CTkLabel(
            self._detail_panel, text="",
            font=ctk.CTkFont(size=18, weight="bold"),
            wraplength=280, justify="center",
        )

        # "GRADE • TYPE" subtitle
        self._d_subtitle_label = ctk.CTkLabel(
            self._detail_panel, text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray55",
        )

        # Spec grid: 4 rows × (static key label + dynamic value label)
        self._d_spec_frame = ctk.CTkFrame(
            self._detail_panel, fg_color=("gray85", "gray18"), corner_radius=8,
        )
        self._d_spec_frame.grid_columnconfigure(1, weight=1)

        self._d_spec_val_labels: List[ctk.CTkLabel] = []
        for idx, key in enumerate(("Location", "Lock Status", "Selling Price (Ask)", "Buying Price (Buy)")):
            ctk.CTkLabel(
                self._d_spec_frame, text=key,
                font=ctk.CTkFont(size=11), text_color="gray55",
            ).grid(row=idx, column=0, padx=16, pady=6, sticky="w")
            val_lbl = ctk.CTkLabel(
                self._d_spec_frame, text="—",
                font=ctk.CTkFont(size=12, weight="bold"), text_color="white",
            )
            val_lbl.grid(row=idx, column=1, padx=16, pady=6, sticky="e")
            self._d_spec_val_labels.append(val_lbl)

        # Item type description text
        self._d_desc_label = ctk.CTkLabel(
            self._detail_panel, text="",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="gray50",
            wraplength=280, justify="center",
        )

        # Strong reference to the current CTkImage — prevents garbage collection
        self._d_ctk_image: Optional[ctk.CTkImage] = None

    def _create_inventory_rows(self):
        """Create rows inside scroll frame once, binding click events to details panel."""
        for item in self._items_list:
            color  = GRADE_COLORS.get(item["grade"], "white")
            row_bg = self._row_bg

            row_f = tk.Frame(self._inv_scroll, bg=row_bg, height=38)
            row_f.pack(fill="x", padx=6, pady=2)
            row_f.grid_columnconfigure(1, weight=1)
            row_f.grid_propagate(False)
            item["row_frame"] = row_f

            # Create a premium styled badge or image label using ctk.CTkLabel
            icon_label = ctk.CTkLabel(
                row_f,
                text="",
                width=24,
                height=24,
                corner_radius=6,
                fg_color="transparent"
            )

            loaded = False
            if item["img_data"]:
                try:
                    pil_img = Image.open(io.BytesIO(item["img_data"])).resize((24, 24), Image.LANCZOS)
                    ctk_img  = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(24, 24))
                    icon_label.configure(image=ctk_img, text="", fg_color="transparent")
                    loaded = True
                except Exception:
                    pass
            if not loaded:
                icon_label.configure(
                    text=item["type"][:1].upper() if item["type"] else "?",
                    font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                    text_color="gray70", fg_color="#424242"
                )
                if item.get("icon_url"):
                    self._fetch_image_async(item, row_f, icon_label, item["icon_url"])
            icon_label.grid(row=0, column=0, padx=8, pady=7, sticky="w")

            lbl_name = tk.Label(
                row_f, text=item["name"],
                font=("Segoe UI", 12, "bold"),
                fg=color, bg=row_bg, anchor="w",
            )
            lbl_name.grid(row=0, column=1, padx=4, pady=5, sticky="w")

            lbl_loc = tk.Label(
                row_f, text=item["location"],
                font=("Segoe UI", 10),
                fg="#888888", bg=row_bg,
            )
            lbl_loc.grid(row=0, column=2, padx=8, pady=5, sticky="e")

            lbl_lock = tk.Label(
                row_f, text="🔒" if item["is_blocked"] else "",
                font=("Segoe UI", 11),
                fg="#E8695A", bg=row_bg,
            )
            lbl_lock.grid(row=0, column=3, padx=8, pady=5, sticky="e")

            for w in [row_f, icon_label, lbl_name, lbl_loc, lbl_lock]:
                w.bind("<Button-1>", lambda e, it=item: self._select_item_row(it))
                w.bind("<Enter>",    lambda e, rf=row_f: self._on_row_hover_enter(rf))
                w.bind("<Leave>",    lambda e, it=item, rf=row_f: self._on_row_hover_leave(it, rf))

    def _on_row_hover_enter(self, row_frame):
        if row_frame != self._selected_row_frame:
            row_frame.configure(bg=self._row_hover)
            for w in row_frame.winfo_children():
                if isinstance(w, tk.Label):
                    w.configure(bg=self._row_hover)

    def _on_row_hover_leave(self, item, row_frame):
        if row_frame != self._selected_row_frame:
            row_frame.configure(bg=self._row_bg)
            for w in row_frame.winfo_children():
                if isinstance(w, tk.Label):
                    w.configure(bg=self._row_bg)

    def _select_item_row(self, item):
        """Highlight row and update detail card on the right."""
        if self._selected_row_frame and self._selected_row_frame.winfo_exists():
            self._selected_row_frame.configure(bg=self._row_bg)
            for w in self._selected_row_frame.winfo_children():
                if isinstance(w, tk.Label):
                    w.configure(bg=self._row_bg)

        self._selected_row_frame = item["row_frame"]
        if self._selected_row_frame:
            self._selected_row_frame.configure(bg=self._row_sel)
            for w in self._selected_row_frame.winfo_children():
                if isinstance(w, tk.Label):
                    w.configure(bg=self._row_sel)

        self._update_detail_card(item)

    def _show_empty_detail_placeholder(self):
        """Hide all detail content widgets and show the centered 'No items found' label."""
        for w in (self._d_img_container, self._d_name_label, self._d_subtitle_label,
                  self._d_spec_frame, self._d_desc_label):
            w.pack_forget()
        self._d_placeholder.place(relx=0.5, rely=0.5, anchor="center")

    def _update_detail_card(self, item):
        """Update the right-side detail panel for the selected item.
        Reuses pre-created widgets via configure() — no widget destruction or recreation.
        """
        self._d_placeholder.place_forget()

        # Destroy existing label inside container to avoid configure cache bug
        if self._d_img_label is not None:
            try:
                self._d_img_label.destroy()
            except Exception:
                pass
            self._d_img_label = None

        # 1. Image (128×128) or fallback initial indicator
        loaded = False
        if item["img_data"]:
            try:
                pil_img = Image.open(io.BytesIO(item["img_data"]))
                self._d_ctk_image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(128, 128))
                self._d_img_label = ctk.CTkLabel(
                    self._d_img_container,
                    image=self._d_ctk_image, text="",
                    fg_color="transparent", corner_radius=0,
                )
                loaded = True
            except Exception:
                pass
        if not loaded:
            self._d_ctk_image = None
            self._d_img_label = ctk.CTkLabel(
                self._d_img_container,
                image=None,
                text=item["type"][:1].upper() if item["type"] else "?",
                font=ctk.CTkFont(size=48, weight="bold"),
                text_color="gray50",
                fg_color=("gray80", "gray20"),
                corner_radius=12,
            )
        self._d_img_label.pack(fill="both", expand=True)
        self._d_img_container.pack(pady=(28, 16))

        # 2. Item name in rarity color
        self._d_name_label.configure(
            text=item["name"],
            text_color=GRADE_COLORS.get(item["grade"], "white"),
        )
        self._d_name_label.pack(padx=16, pady=4)

        # 3. "GRADE • TYPE" subtitle
        self._d_subtitle_label.configure(text=f"{item['grade']} • {item['type'].upper()}")
        self._d_subtitle_label.pack(pady=(0, 20))

        # 4. Spec values — only update the dynamic value labels, keys are static
        currency_sym = _cfg.get_currency_symbol()

        def fmt_price(val: Optional[float]) -> str:
            if val is None:
                return "-"
            if currency_sym in ("Rp", "₩", "₫", "¥"):
                return f"{currency_sym} {int(val):,}"
            return f"{currency_sym} {val:,.2f}"

        spec_data = [
            (item["location"],                                           "white"),
            ("Locked 🔒" if item["is_blocked"] else "Unlocked",         "#E8695A" if item["is_blocked"] else "white"),
            (fmt_price(item["ask_price"]),                               "#7CE937" if item["ask_price"] is not None else "white"),
            (fmt_price(item["buy_price"]),                               "white"),
        ]
        for lbl, (text, color) in zip(self._d_spec_val_labels, spec_data):
            lbl.configure(text=text, text_color=color)
        self._d_spec_frame.pack(fill="x", padx=20, pady=10)

        # 5. Item type description
        item_type = item["type"].lower()
        if item_type == "gear":
            desc = "Combat equipment (Gear) that can be used by your hero to boost combat stats and attributes."
        elif item_type == "material":
            desc = "Essential crafting materials used in the Cube for synthesis, engraving, or offering."
        else:
            desc = "A valuable item synced from your Task Bar Hero save game."
        self._d_desc_label.configure(text=desc)
        self._d_desc_label.pack(padx=20, pady=(20, 10))

    def _on_filter_changed(self, *_):
        """Handle search input or sorting dropdown changes."""
        query = self._search_var.get().lower().strip()
        sort_mode = self._sort_menu.get()

        # 1. Apply Sorting
        if sort_mode == "Sort: Alphabetical A-Z":
            self._items_list.sort(key=lambda x: x["name"].lower())
        elif sort_mode == "Sort: Alphabetical Z-A":
            self._items_list.sort(key=lambda x: x["name"].lower(), reverse=True)
        elif sort_mode == "Sort: Highest Price":
            # Sort by ask_price (fallback to 0.0 if None)
            self._items_list.sort(key=lambda x: x["ask_price"] or 0.0, reverse=True)
        elif sort_mode == "Sort: Highest Rarity":
            self._items_list.sort(key=lambda x: RARITY_WEIGHTS.get(x["grade"], 0), reverse=True)

        # 2. Update Grid Packing & Visibility
        self._update_scroll_packing(query)

        # 3. Auto select first visible item
        visible_items = []
        for item in self._items_list:
            name = item["name"].lower()
            itype = item["type"].lower()
            loc = item["location"].lower()
            if not query or query in name or query in itype or query in loc:
                visible_items.append(item)

        if visible_items:
            self._select_item_row(visible_items[0])
        else:
            self._show_empty_detail_placeholder()

    def _fetch_image_async(self, item, row_frame, icon_label, url: str):
        def _fetch():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                save_cached_image(item["name"], data)
                item["img_data"] = data
                self.after(0, lambda: self._on_image_downloaded(item, row_frame, icon_label))
            except Exception as exc:
                log.debug("SaveInspector image fetch failed for %s: %s", item["name"], exc)
        threading.Thread(target=_fetch, daemon=True).start()

    def _on_image_downloaded(self, item, row_frame, icon_label):
        if row_frame.winfo_exists() and icon_label.winfo_exists():
            try:
                pil_img = Image.open(io.BytesIO(item["img_data"])).resize((24, 24), Image.LANCZOS)
                ctk_img  = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(24, 24))
                icon_label.configure(image=ctk_img, text="", fg_color="transparent")
            except Exception:
                pass
        if self._selected_row_frame == row_frame:
            self._update_detail_card(item)

    def _update_scroll_packing(self, query=""):
        """Show or hide rows in scroll container according to search query."""
        # Unpack all first to reset visual order
        for item in self._items_list:
            if item["row_frame"]:
                item["row_frame"].pack_forget()

        for item in self._items_list:
            row_frame = item["row_frame"]
            if not row_frame:
                continue

            name = item["name"].lower()
            itype = item["type"].lower()
            loc = item["location"].lower()

            if not query or query in name or query in itype or query in loc:
                row_frame.pack(fill="x", padx=6, pady=2)

    def _center_on(self, parent):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 100 or h < 100:
            w, h = 920, 600
        px = parent.winfo_x() + parent.winfo_width() // 2 - w // 2
        py = parent.winfo_y() + parent.winfo_height() // 2 - h // 2
        self.geometry(f"{w}x{h}+{max(px, 0)}+{max(py, 0)}")
