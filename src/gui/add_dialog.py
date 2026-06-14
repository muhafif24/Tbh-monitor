import tkinter as tk
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

# Plain tk item rows — no internal tk.Canvas; much faster than CTkButton
_BATCH_SIZE         = 100  # plain-tk rows are cheap, build more per tick
_SEARCH_DEBOUNCE_MS = 150  # ms to wait after last keystroke before filtering

# Color palette (matched to CTkScrollableFrame fg_color=("gray85","gray18"))
_COLORS_DARK  = dict(row="#2e2e2e", hover="#474747", sel="#525252",
                     sel_fg="#f0f0f0", txt_avail="#cccccc", txt_sold="#808080")
_COLORS_LIGHT = dict(row="#d9d9d9", hover="#bfbfbf", sel="#a6a6a6",
                     sel_fg="#1a1a1a", txt_avail="#262626", txt_sold="#808080")
_ROW_FONT     = ("Segoe UI", 11)
_DOT_FONT     = ("Segoe UI", 12)
_OWN_FONT     = ("Segoe UI", 11, "bold")


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
        self.attributes('-alpha', 0.0)
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
        self._item_buttons: list = []   # (tk.Label btn, hash_name, is_available, owned)
        self._filter = _FILTER_ALL
        self._search_after_id = None    # debounce timer id
        self._loading_label   = None    # progress label during deferred build

        # Resolve theme colors once (won't change while dialog is open)
        _c = _COLORS_DARK if ctk.get_appearance_mode() == "Dark" else _COLORS_LIGHT
        self._row_bg    = _c["row"]
        self._row_hover = _c["hover"]
        self._row_sel   = _c["sel"]
        self._sel_fg    = _c["sel_fg"]
        self._txt_avail = _c["txt_avail"]
        self._txt_sold  = _c["txt_sold"]

        if self._text_mode:
            self.geometry("440x230")
            self._build_text_ui()
        else:
            self.geometry("580x520")
            self._build_picker_ui()

        self._center_on(parent)
        self.attributes('-alpha', 1.0)

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

        if self._catalog:
            self._loading_label = ctk.CTkLabel(
                self._list_frame,
                text="Loading items...",
                font=ctk.CTkFont(size=11),
                text_color="gray50",
            )
            self._loading_label.grid(row=0, column=0, pady=16)
            self.after(0, lambda: self._deferred_build_list(0))

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

        # Row 4: manual input (collapsed by default)
        self._manual_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._manual_frame.grid(row=4, column=0, padx=16, pady=(0, 0), sticky="ew")
        self._manual_frame.grid_columnconfigure(1, weight=1)
        self._manual_frame.grid_remove()

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

        self._update_counter(0)

    def _add_item_button(self, hash_name: str, item_type: str, is_available: bool, owned: int = 0):
        """
        Create one item row using plain tk widgets (tk.Frame + tk.Label).
        Plain tk has no internal Canvas per widget — ~10x faster than CTkButton.
        """
        dot, dot_color = _DOT_AVAILABLE if is_available else _DOT_SOLDOUT
        name_color     = self._txt_avail if is_available else self._txt_sold
        row_bg         = self._row_bg

        row_frame = tk.Frame(self._list_frame, bg=row_bg, height=30)
        row_idx   = 1 + len(self._item_buttons)   # row 0 = loading_label slot
        row_frame.grid(row=row_idx, column=0, sticky="ew", padx=4, pady=1)
        row_frame.grid_columnconfigure(1, weight=1)
        row_frame.grid_propagate(False)

        dot_lbl = tk.Label(
            row_frame, text=dot, fg=dot_color, bg=row_bg,
            font=_DOT_FONT, width=2,
        )
        dot_lbl.grid(row=0, column=0, padx=(6, 2))

        label = f"{hash_name}  ·  {item_type}" if item_type else hash_name
        btn = tk.Label(
            row_frame, text=label, fg=name_color, bg=row_bg,
            font=_ROW_FONT, anchor="w", cursor="hand2",
        )
        btn.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        if owned > 0:
            own_lbl = tk.Label(
                row_frame, text=f"×{owned}", fg=_OWNED_COLOR, bg=row_bg,
                font=_OWN_FONT, width=4, anchor="e",
            )
            own_lbl.grid(row=0, column=2, padx=(0, 8))

        # Hover + click bindings on all sub-widgets
        hover_bg = self._row_hover
        sel_bg   = self._row_sel

        def _on_enter(e, hn=hash_name):
            if self._selected == hn:
                return
            row_frame.configure(bg=hover_bg)
            for w in row_frame.winfo_children():
                w.configure(bg=hover_bg)

        def _on_leave(e, hn=hash_name):
            if self._selected == hn:
                return
            row_frame.configure(bg=row_bg)
            for w in row_frame.winfo_children():
                w.configure(bg=row_bg)

        def _on_click(e, hn=hash_name):
            self._select(hn)

        for widget in (row_frame, dot_lbl, btn):
            widget.bind("<Enter>",    _on_enter)
            widget.bind("<Leave>",    _on_leave)
            widget.bind("<Button-1>", _on_click)

        self._item_buttons.append((btn, hash_name, is_available, owned))

    def _deferred_build_list(self, start_idx: int):
        """Build _BATCH_SIZE item rows per after() tick, keeping the UI responsive."""
        if not self.winfo_exists():
            return
        total   = len(self._catalog)
        end_idx = min(start_idx + _BATCH_SIZE, total)

        for i in range(start_idx, end_idx):
            item = self._catalog[i]
            self._add_item_button(
                item.hash_name, item.item_type,
                getattr(item, "available", True),
                getattr(item, "owned", 0),
            )

        if end_idx < total:
            if self._loading_label and self._loading_label.winfo_exists():
                pct = int(end_idx / total * 100)
                self._loading_label.configure(text=f"Loading items... {pct}%")
            self.after(0, lambda: self._deferred_build_list(end_idx))
        else:
            if self._loading_label and self._loading_label.winfo_exists():
                self._loading_label.grid_remove()
                self._loading_label = None
            self._apply_search_filter()

    # ── Selection ─────────────────────────────────────────────────────────────

    def _select(self, hash_name: str):
        prev = self._selected
        self._selected = hash_name

        # Deselect previous
        if prev and prev != hash_name:
            for btn, name, available, _ in self._item_buttons:
                if name == prev:
                    nc = self._txt_avail if available else self._txt_sold
                    f  = btn.master
                    f.configure(bg=self._row_bg)
                    for w in f.winfo_children(): w.configure(bg=self._row_bg)
                    btn.configure(fg=nc)
                    break

        # Highlight new selection
        for btn, name, _, _ in self._item_buttons:
            if name == hash_name:
                f = btn.master
                f.configure(bg=self._row_sel)
                for w in f.winfo_children(): w.configure(bg=self._row_sel)
                btn.configure(fg=self._sel_fg)
                break

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
        self._apply_search_filter()

    def _on_search_change(self, *_):
        """Debounce: wait _SEARCH_DEBOUNCE_MS after last keystroke before filtering."""
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(_SEARCH_DEBOUNCE_MS, self._apply_search_filter)

    def _apply_search_filter(self):
        """Apply current search query + filter to the item list."""
        if not self.winfo_exists():
            return
        self._search_after_id = None
        query = self._search_var.get().lower().strip()

        for btn, _, _a, _ow in self._item_buttons:
            btn.master.grid_remove()

        visible = 0
        for btn, name, available, owned in self._item_buttons:
            if not self._passes_filter(available, owned):
                continue
            cat      = self._catalog_dict.get(name)
            type_str = cat.item_type.lower() if cat else ""
            if not query or query in name.lower() or query in type_str:
                btn.master.grid()
                visible += 1

        # Re-apply selection highlight if selected item is visible
        if self._selected:
            for btn, name, _, _ in self._item_buttons:
                if name == self._selected:
                    f = btn.master
                    f.configure(bg=self._row_sel)
                    for w in f.winfo_children(): w.configure(bg=self._row_sel)
                    btn.configure(fg=self._sel_fg)
                    break

        self._update_counter(visible, query)

    def _update_counter(self, visible: int, query: str = ""):
        n_total     = len(self._item_buttons)
        n_available = sum(1 for _, _, av, _ow in self._item_buttons if av)
        n_soldout   = n_total - n_available
        n_owned     = sum(1 for _, _, _av, ow in self._item_buttons if ow > 0)

        if query or self._filter != _FILTER_ALL:
            self._counter_label.configure(text=f"{visible} of {n_total} items")
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
            self._selected = None
        else:
            self._manual_frame.grid()
            self._link_manual.configure(text="↑ Close manual input")
            self._selected = None
            # Reset all visible row colours
            for btn, _, available, _ in self._item_buttons:
                nc = self._txt_avail if available else self._txt_sold
                f  = btn.master
                f.configure(bg=self._row_bg)
                for w in f.winfo_children(): w.configure(bg=self._row_bg)
                btn.configure(fg=nc)
            self._manual_entry.focus()

    # ── Validation + confirm ──────────────────────────────────────────────────

    def _on_add(self):
        if self._text_mode:
            name = self._entry.get().strip()
            if not name:
                self._show_error("Item name cannot be empty.")
                return
        elif self._manual_frame.winfo_ismapped():
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
