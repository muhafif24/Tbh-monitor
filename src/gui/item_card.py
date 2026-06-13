import io
import logging
import urllib.parse
import webbrowser
from typing import Callable, Optional

import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image

from .. import config as _cfg
from ..steam_api import APP_ID

_MARKET_BASE = f"https://steamcommunity.com/market/listings/{APP_ID}/"

log = logging.getLogger(__name__)

_TREND_UP   = ("▲", "#4CAF50")
_TREND_DOWN = ("▼", "#E8695A")
_TREND_FLAT = ("—", "gray55")
_GRAPH_BG   = "#1e1e1e"


class ItemCard(ctk.CTkFrame):
    """
    Two-section card: [image | info block] on top, price history graph below.

    Thread safety: all configure() calls must happen on the main thread.
    Use MainWindow.after(0, lambda: card.method()) when calling from a worker thread.
    """

    HEIGHT = 240

    def __init__(
        self,
        parent,
        item_name: str,
        color_hex: str = "FFFFFF",
        on_delete: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent, height=self.HEIGHT, corner_radius=8,
                         fg_color=("gray90", "gray16"))
        self.grid_propagate(False)

        self._item_name = item_name
        self._color_hex = color_hex
        self._on_delete = on_delete
        self._currency_symbol = _cfg.get_currency_symbol()
        self._ctk_image = None
        self._fig = None
        self._ax = None
        self._mpl_canvas = None

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=0)  # image column (fixed)
        self.grid_columnconfigure(1, weight=1)  # info column (expands)

        # ── Image ─────────────────────────────────────────────────────────────
        self._img_label = ctk.CTkLabel(
            self, text="···",
            width=80, height=80,
            font=ctk.CTkFont(size=11),
            text_color="gray45",
            fg_color=("gray80", "gray22"),
            corner_radius=6,
        )
        self._img_label.grid(row=0, column=0, padx=(12, 8), pady=(14, 0), sticky="n")

        # ── Info block ────────────────────────────────────────────────────────
        _info = ctk.CTkFrame(self, fg_color="transparent")
        _info.grid(row=0, column=1, padx=(0, 10), pady=(10, 0), sticky="nsew")
        _info.grid_columnconfigure(0, weight=1)
        _info.grid_columnconfigure(1, weight=0)

        # Row 0: item name (left) + delete button (right)
        self._name_label = ctk.CTkLabel(
            _info,
            text=self._item_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=f"#{self._color_hex}",
            anchor="w",
            wraplength=280,
            cursor="hand2",
        )
        self._name_label.grid(row=0, column=0, sticky="w", pady=(0, 1))
        self._name_label.bind("<Button-1>", self._open_market_page)

        self._btn_del = ctk.CTkButton(
            _info,
            text="✕",
            width=26, height=26,
            fg_color="transparent",
            text_color="gray45",
            hover_color=("gray75", "gray28"),
            font=ctk.CTkFont(size=11),
            command=self._handle_delete,
        )
        self._btn_del.grid(row=0, column=1, padx=(6, 0))

        # Row 1: item type / grade
        self._type_label = ctk.CTkLabel(
            _info, text="",
            font=ctk.CTkFont(size=10),
            text_color="gray50",
            anchor="w",
        )
        self._type_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 5))

        # Row 2: ask price + trend arrow
        _ask = ctk.CTkFrame(_info, fg_color="transparent")
        _ask.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 2))

        ctk.CTkLabel(
            _ask, text="Ask :",
            font=ctk.CTkFont(size=10),
            text_color="gray50",
            width=32, anchor="w",
        ).pack(side="left")

        self._price_label = ctk.CTkLabel(
            _ask, text="—",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="white",
            anchor="w",
        )
        self._price_label.pack(side="left", padx=(4, 4))

        self._trend_label = ctk.CTkLabel(
            _ask, text="",
            font=ctk.CTkFont(size=14),
            anchor="w",
        )
        self._trend_label.pack(side="left")

        # Row 3: highest buy order
        _buy = ctk.CTkFrame(_info, fg_color="transparent")
        _buy.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 2))

        ctk.CTkLabel(
            _buy, text="Buy :",
            font=ctk.CTkFont(size=10),
            text_color="gray50",
            width=32, anchor="w",
        ).pack(side="left")

        self._buy_label = ctk.CTkLabel(
            _buy, text="—",
            font=ctk.CTkFont(size=11),
            text_color="#4a9eff",
            anchor="w",
        )
        self._buy_label.pack(side="left", padx=(4, 0))

        # Row 4: median price + 24h volume
        self._meta_label = ctk.CTkLabel(
            _info, text="",
            font=ctk.CTkFont(size=10),
            text_color="gray50",
            anchor="w",
        )
        self._meta_label.grid(row=4, column=0, columnspan=2, sticky="w")

        # ── Graph slot ────────────────────────────────────────────────────────
        self._graph_slot = ctk.CTkFrame(
            self, height=100,
            fg_color=("gray85", "gray20"),
            corner_radius=4,
        )
        self._graph_slot.grid(row=1, column=0, columnspan=2, padx=10, pady=(8, 10), sticky="ew")
        self._graph_slot.grid_propagate(False)

        self._graph_placeholder = ctk.CTkLabel(
            self._graph_slot,
            text="No history data",
            font=ctk.CTkFont(size=10),
            text_color="gray45",
        )
        self._graph_placeholder.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            self._graph_slot,
            text="USD",
            font=ctk.CTkFont(size=8),
            text_color="gray40",
            fg_color="transparent",
        ).place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_image(self, image_bytes: bytes):
        """Decode bytes → CTkImage. Must be called from the main thread."""
        try:
            pil_img = Image.open(io.BytesIO(image_bytes)).resize((80, 80), Image.LANCZOS)
            self._ctk_image = ctk.CTkImage(
                light_image=pil_img, dark_image=pil_img, size=(80, 80)
            )
            self._img_label.configure(image=self._ctk_image, text="")
        except Exception:
            log.warning("Failed to decode image for item: %s", self._item_name)

    def set_item_type(self, item_type: str):
        """Update the type/grade subtitle. Must be called from the main thread."""
        self._type_label.configure(text=item_type)

    def update_price(self, result: dict, last_price: Optional[float] = None):
        """
        Update ask price, trend indicator, median price, and volume.
        result from get_price():
          {"status": "OK", "price": float, "median_price": float|None, "volume": int|None}
          {"status": "SOLD_OUT"} | {"status": "ERROR"}
        Must be called from the main thread.
        """
        status = result.get("status")

        if status == "SOLD_OUT":
            self._price_label.configure(text="No listings", text_color="gray50")
            self._trend_label.configure(text="")
            self._meta_label.configure(text="")
            return

        if status == "ERROR":
            self._price_label.configure(text="Fetch error", text_color="#E8695A")
            self._trend_label.configure(text="")
            return

        price = result["price"]
        sym = self._currency_symbol
        self._price_label.configure(text=f"{sym} {price:,.0f}", text_color="white")
        self._set_trend(price, last_price)

        parts = []
        median = result.get("median_price")
        volume = result.get("volume")
        if median:
            parts.append(f"Med  {sym} {median:,.0f}")
        if volume is not None:
            parts.append(f"Vol  {volume:,}/day")
        self._meta_label.configure(text="   ·   ".join(parts))

    def update_buy_orders(self, buy_orders: dict):
        """
        Update the buy order row.
        buy_orders: {"highest_price": float | None, "count": int}
        Must be called from the main thread.
        """
        hp = buy_orders.get("highest_price")
        count = buy_orders.get("count", 0)
        if hp:
            self._buy_label.configure(
                text=f"{self._currency_symbol} {hp:,.0f}   ({count:,} orders)",
                text_color="#4a9eff",
            )
        else:
            self._buy_label.configure(text="No buy orders", text_color="gray50")

    def get_graph_slot(self) -> ctk.CTkFrame:
        """Return the graph slot frame."""
        return self._graph_slot

    def set_rarity_color(self, color_hex: str):
        """Update name label color to match item rarity. Must be called from main thread."""
        self._color_hex = color_hex
        self._name_label.configure(text_color=f"#{color_hex}")

    def set_currency_symbol(self, symbol: str):
        """
        Update the currency symbol used in price/buy/median labels.
        Clears displayed prices so stale values aren't shown in the wrong currency.
        Must be called from the main thread.
        """
        self._currency_symbol = symbol
        self._price_label.configure(text="—", text_color="white")
        self._trend_label.configure(text="")
        self._meta_label.configure(text="")
        self._buy_label.configure(text="—", text_color="#4a9eff")

    def hide_graph_placeholder(self):
        self._graph_placeholder.place_forget()

    def update_graph(self, history: list):
        """
        Embed or refresh the price history chart.
        history: list of [date_str, price_usd, volume] from Steam line1.
        Must be called from the main thread.
        """
        if self._mpl_canvas is None:
            self._create_graph()

        prices = [row[1] for row in history] if history else []
        self._ax.clear()
        self._ax.set_facecolor(_GRAPH_BG)

        if prices:
            self._ax.plot(prices, color="#4a9eff", linewidth=0.9, antialiased=True)
            self._ax.margins(x=0.01, y=0.15)
        else:
            self._ax.text(
                0.5, 0.5, "No history data",
                ha="center", va="center",
                transform=self._ax.transAxes,
                color="gray", fontsize=7,
            )

        for spine in self._ax.spines.values():
            spine.set_visible(False)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._mpl_canvas.draw()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _create_graph(self):
        """Build the matplotlib figure and embed it in the graph slot frame."""
        self._fig = Figure(figsize=(5, 0.9), dpi=80, facecolor=_GRAPH_BG)
        self._fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor(_GRAPH_BG)

        self._mpl_canvas = FigureCanvasTkAgg(self._fig, master=self._graph_slot)
        self._mpl_canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.hide_graph_placeholder()

    def _set_trend(self, current: float, last: Optional[float]):
        if last is None:
            self._trend_label.configure(text="")
            return
        if current > last:
            symbol, color = _TREND_UP
        elif current < last:
            symbol, color = _TREND_DOWN
        else:
            symbol, color = _TREND_FLAT
        self._trend_label.configure(text=symbol, text_color=color)

    def _open_market_page(self, _event=None):
        market_url = _MARKET_BASE + urllib.parse.quote(self._item_name, safe="")
        webbrowser.open(f"steam://openurl/{market_url}")

    def _handle_delete(self):
        if self._on_delete:
            self._on_delete(self._item_name)
