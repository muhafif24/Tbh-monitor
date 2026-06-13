from typing import Callable, List, Optional

import customtkinter as ctk

MAX_ITEMS = 5

# Availability dot indicators
_DOT_AVAILABLE = ("●", "#4CAF50")   # green dot — active listings exist
_DOT_SOLDOUT   = ("○", "#888888")   # hollow dot — sold out
_OWNED_COLOR   = "#E8C547"          # gold — owned count from savegame sync

_FILTER_ALL     = "All"
_FILTER_OWNED   = "Owned"
_FILTER_LISTING = "Listed"
_FILTER_SOLDOUT = "Sold out"


class AddItemDialog(ctk.CTkToplevel):
    """
    Modal dialog to add a new tracked item.

    Picker mode (catalog provided):
      - Search box filters items as-you-type.
      - Filter buttons: All / Owned / Listed / Sold out.
      - Counter updates dynamically showing filtered / total counts.
      - ● green dot = active listings on the Steam market.
      - ○ gray dot  = sold out (seen before, currently no listings).
      - ×N gold badge = owned count from the savegame (⇄ Sync).
      - Sold-out items can still be added (card shows "No listings").

    Text mode (catalog empty / not ready):
      - Manual hash-name input fallback.
    """

    def __init__(
        self,
        parent,
        current_names: List[str],
        on_confirm: Callable[[str], None],
        catalog=None,
    ):
        super().__init__(parent)
        self.title("Add Item")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()

        self._current_names = list(current_names)
        self._on_confirm    = on_confirm
        self._catalog: list = list(catalog) if catalog else []
        self._catalog_dict  = {c.hash_name: c for c in self._catalog}
        self._text_mode     = not bool(self._catalog)
        self._selected: Optional[str] = None
        self._item_buttons: list = []   # (CTkButton, hash_name, is_available, owned)
        self._filter = _FILTER_ALL

        if self._text_mode:
            self.geometry("440x230")
            self._build_text_ui()
        else:
            self.geometry("580x520")
            self._build_picker_ui()

        self._center_on(parent)

    # ── Text-input fallback ───────────────────────────────────────────────────

    def _build_text_ui(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Steam Market Hash Name",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(18, 4), sticky="w")

        self._entry = ctk.CTkEntry(
            self, placeholder_text="e.g. Frozen Orb (Immortal) A",
            width=400, height=36,
        )
        self._entry.grid(row=1, column=0, padx=20, pady=(0, 4))
        self._entry.bind("<Return>", lambda _e: self._on_add())
        self._entry.focus()

        ctk.CTkLabel(
            self,
            text="Enter the name exactly as it appears on Steam Market.",
            font=ctk.CTkFont(size=10), text_color="gray50",
        ).grid(row=2, column=0, padx=20, sticky="w")

        ctk.CTkLabel(
            self,
            text="Catalog not ready — click '↻ Catalog' in the header after closing this dialog.",
            font=ctk.CTkFont(size=10), text_color="#E8A838",
        ).grid(row=3, column=0, padx=20, pady=(2, 0), sticky="w")

        self._error_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color="#E8695A",
        )
        self._error_label.grid(row=4, column=0, padx=20, pady=(3, 0), sticky="w")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=5, column=0, padx=20, pady=(10, 18), sticky="e")
        ctk.CTkButton(
            btn_row, text="Cancel", width=90, fg_color="transparent",
            border_width=1, border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"), hover_color=("gray75", "gray28"),
            command=self.destroy,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Add Item", width=100, command=self._on_add).pack(side="left")

    # ── Searchable picker ─────────────────────────────────────────────────────

    def _build_picker_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # row 2 = scrollable list expands

        # Row 0: search entry
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", self._on_search_change)
        search_entry = ctk.CTkEntry(
            self, textvariable=self._search_var,
            placeholder_text="Search items...",
            height=36, font=ctk.CTkFont(size=12),
        )
        search_entry.grid(row=0, column=0, padx=16, pady=(16, 2), sticky="ew")
        search_entry.focus()
        search_entry.bind("<Return>", lambda _e: self._on_add())

        # Row 1: filter buttons + dynamic counter label
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.grid(row=1, column=0, padx=16, pady=(0, 4), sticky="ew")
        filter_row.grid_columnconfigure(1, weight=1)

        self._filter_seg = ctk.CTkSegmentedButton(
            filter_row,
            values=[_FILTER_ALL, _FILTER_OWNED, _FILTER_LISTING, _FILTER_SOLDOUT],
            command=self._on_filter_change,
            font=ctk.CTkFont(size=10),
            height=24,
        )
        self._filter_seg.set(_FILTER_ALL)
        self._filter_seg.grid(row=0, column=0, sticky="w")

        self._counter_label = ctk.CTkLabel(
            filter_row, text="",
            font=ctk.CTkFont(size=10), text_color="gray50", anchor="e",
        )
        self._counter_label.grid(row=0, column=1, padx=(8, 2), sticky="e")

        # Row 2: scrollable item list
        self._list_frame = ctk.CTkScrollableFrame(
            self, fg_color=("gray85", "gray18"), corner_radius=6,
        )
        self._list_frame.grid(row=2, column=0, padx=16, pady=(0, 6), sticky="nsew")
        self._list_frame.grid_columnconfigure(0, weight=1)

        for item in self._catalog:
            is_available = getattr(item, "available", True)
            owned = getattr(item, "owned", 0)
            self._add_item_button(item.hash_name, item.item_type, is_available, owned)

        # Row 3: legend + error
        legend_row = ctk.CTkFrame(self, fg_color="transparent")
        legend_row.grid(row=3, column=0, padx=16, pady=(0, 0), sticky="ew")
        legend_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            legend_row,
            text=f"{_DOT_AVAILABLE[0]} Listed    {_DOT_SOLDOUT[0]} Sold out    ×N Owned",
            font=ctk.CTkFont(size=10), text_color="gray45",
        ).grid(row=0, column=0, sticky="w")

        self._error_label = ctk.CTkLabel(
            legend_row, text="", font=ctk.CTkFont(size=11), text_color="#E8695A",
        )
        self._error_label.grid(row=0, column=1, sticky="e")

        # Row 4: manual input (collapsed by default, for sold-out items not in the list)
        self._manual_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._manual_frame.grid(row=4, column=0, padx=16, pady=(0, 0), sticky="ew")
        self._manual_frame.grid_columnconfigure(1, weight=1)
        self._manual_frame.grid_remove()   # hidden by default

        ctk.CTkLabel(
            self._manual_frame, text="Name:",
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).grid(row=0, column=0, padx=(0, 6), sticky="w")

        self._manual_entry = ctk.CTkEntry(
            self._manual_frame,
            placeholder_text='e.g. Soulstone - Normal',
            height=30, font=ctk.CTkFont(size=11),
        )
        self._manual_entry.grid(row=0, column=1, sticky="ew")
        self._manual_entry.bind("<Return>", lambda _e: self._on_add())

        # Row 5: buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=5, column=0, padx=16, pady=(4, 14), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)

        self._link_manual = ctk.CTkButton(
            btn_row, text="Not in the list? Enter manually →",
            fg_color="transparent", text_color="gray45",
            hover_color=("gray85", "gray20"),
            font=ctk.CTkFont(size=10), anchor="w", height=22,
            command=self._toggle_manual,
        )
        self._link_manual.grid(row=0, column=0, sticky="w")

        right_btns = ctk.CTkFrame(btn_row, fg_color="transparent")
        right_btns.grid(row=0, column=1, sticky="e")
        ctk.CTkButton(
            right_btns, text="Cancel", width=90, fg_color="transparent",
            border_width=1, border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"), hover_color=("gray75", "gray28"),
            command=self.destroy,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(right_btns, text="Add Item", width=100, command=self._on_add).pack(side="left")

        # Initialize counter
        self._update_counter(len(self._item_buttons))

    def _add_item_button(self, hash_name: str, item_type: str, is_available: bool, owned: int = 0):
        """Create one row button for the scrollable list."""
        dot, dot_color = _DOT_AVAILABLE if is_available else _DOT_SOLDOUT
        type_str = item_type or ""
        name_color = ("gray15", "gray80") if is_available else ("gray50", "gray50")

        row_frame = ctk.CTkFrame(
            self._list_frame, fg_color="transparent", height=30,
        )
        row_frame.pack(fill="x", padx=4, pady=1)
        row_frame.grid_columnconfigure(1, weight=1)
        row_frame.grid_propagate(False)

        # Availability dot
        dot_label = ctk.CTkLabel(
            row_frame, text=dot, font=ctk.CTkFont(size=12),
            text_color=dot_color, width=18,
        )
        dot_label.grid(row=0, column=0, padx=(6, 2))

        # Item name + type button
        label = f"{hash_name}  ·  {type_str}" if type_str else hash_name
        btn = ctk.CTkButton(
            row_frame,
            text=label,
            anchor="w",
            fg_color="transparent",
            text_color=name_color,
            hover_color=("gray75", "gray28"),
            font=ctk.CTkFont(size=11),
            height=28,
            command=lambda n=hash_name: self._select(n),
        )
        btn.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        # Owned badge (from savegame sync)
        if owned > 0:
            owned_label = ctk.CTkLabel(
                row_frame, text=f"×{owned}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_OWNED_COLOR, width=36, anchor="e",
            )
            owned_label.grid(row=0, column=2, padx=(0, 8))

        self._item_buttons.append((btn, hash_name, is_available, owned))

    # ── Selection ─────────────────────────────────────────────────────────────

    def _select(self, hash_name: str):
        self._selected = hash_name
        for btn, name, available, _ow in self._item_buttons:
            if name == hash_name:
                btn.configure(fg_color=("gray65", "gray32"), text_color=("gray5", "white"))
            else:
                default = ("gray15", "gray80") if available else ("gray50", "gray50")
                btn.configure(fg_color="transparent", text_color=default)

    # ── Search / filter ───────────────────────────────────────────────────────

    def _passes_filter(self, available: bool, owned: int) -> bool:
        if self._filter == _FILTER_OWNED:
            return owned > 0
        if self._filter == _FILTER_LISTING:
            return available
        if self._filter == _FILTER_SOLDOUT:
            return not available
        return True   # All

    def _on_filter_change(self, value: str):
        self._filter = value
        self._on_search_change()

    def _on_search_change(self, *_):
        query = self._search_var.get().lower().strip()

        # Hide all row frames first (parent of each button)
        for btn, _, _a, _ow in self._item_buttons:
            btn.master.pack_forget()

        visible = 0
        for btn, name, available, owned in self._item_buttons:
            if not self._passes_filter(available, owned):
                continue
            cat      = self._catalog_dict.get(name)
            type_str = cat.item_type.lower() if cat else ""
            if not query or query in name.lower() or query in type_str:
                btn.master.pack(fill="x", padx=4, pady=1)
                visible += 1

        # Restore selection highlight if still visible
        if self._selected:
            for btn, name, _a, _ow in self._item_buttons:
                if name == self._selected:
                    btn.configure(fg_color=("gray65", "gray32"), text_color=("gray5", "white"))

        self._update_counter(visible, query)

    def _update_counter(self, visible: int, query: str = ""):
        n_total     = len(self._item_buttons)
        n_available = sum(1 for _, _, av, _ow in self._item_buttons if av)
        n_soldout   = n_total - n_available
        n_owned     = sum(1 for _, _, _av, ow in self._item_buttons if ow > 0)

        if query or self._filter != _FILTER_ALL:
            self._counter_label.configure(
                text=f"{visible} of {n_total} items"
            )
        else:
            parts = [f"{n_available} listed"]
            if n_soldout:
                parts.append(f"{n_soldout} sold out")
            if n_owned:
                parts.append(f"{n_owned} owned")
            self._counter_label.configure(text="  ·  ".join(parts))

    def _toggle_manual(self):
        """Show/hide the manual text input row."""
        if self._manual_frame.winfo_ismapped():
            self._manual_frame.grid_remove()
            self._link_manual.configure(text="Not in the list? Enter manually →")
            self._selected = None   # clear manual selection when hiding
        else:
            self._manual_frame.grid()
            self._link_manual.configure(text="↑ Close manual input")
            self._selected = None   # deselect list item
            for btn, _, available, _ow in self._item_buttons:
                default = ("gray15", "gray80") if available else ("gray50", "gray50")
                btn.configure(fg_color="transparent", text_color=default)
            self._manual_entry.focus()

    # ── Validation + confirm ──────────────────────────────────────────────────

    def _on_add(self):
        if self._text_mode:
            name = self._entry.get().strip()
            if not name:
                self._show_error("Item name cannot be empty.")
                return
        elif self._manual_frame.winfo_ismapped():
            # Manual input mode (for sold-out items not in the list)
            name = self._manual_entry.get().strip()
            if not name:
                self._show_error("Enter an item name.")
                return
        else:
            name = self._selected
            if not name:
                self._show_error("Select an item from the list first.")
                return

        if len(self._current_names) >= MAX_ITEMS:
            self._show_error(f"Maximum {MAX_ITEMS} items.")
            return
        if name in self._current_names:
            self._show_error("This item is already tracked.")
            return

        self._on_confirm(name)
        self.destroy()

    def _show_error(self, message: str):
        self._error_label.configure(text=message)

    # ── Positioning ───────────────────────────────────────────────────────────

    def _center_on(self, parent):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        px = parent.winfo_x() + parent.winfo_width()  // 2 - w // 2
        py = parent.winfo_y() + parent.winfo_height() // 2 - h // 2
        self.geometry(f"+{max(px, 0)}+{max(py, 0)}")
