import io
import logging
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FuncFormatter
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
        self._current_price_selected = None
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

        self._currency_label = ctk.CTkLabel(
            self._graph_slot,
            text=self._currency_symbol,
            font=ctk.CTkFont(size=8),
            text_color="gray40",
            fg_color="transparent",
        )
        self._currency_label.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)

        # ── Time range filters ────────────────────────────────────────────────
        self._active_range = "Lifetime"
        self._filter_frame = ctk.CTkFrame(self._graph_slot, fg_color="transparent")
        self._filter_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-6, y=2)

        self._filter_buttons = {}
        for r_name in ["Week", "Month", "Year", "Lifetime"]:
            btn = ctk.CTkButton(
                self._filter_frame,
                text=r_name,
                width=34, height=14,
                font=ctk.CTkFont(size=8),
                fg_color="transparent",
                text_color="gray65",
                hover_color="gray30",
                corner_radius=2,
                command=lambda name=r_name: self._on_range_change(name)
            )
            btn.pack(side="left", padx=1)
            self._filter_buttons[r_name] = btn

        self._update_filter_buttons_ui()

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
        prev_price = self._current_price_selected
        self._current_price_selected = price
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

        # Only redraw graph when price changed — exchange rate (IDR/USD) is derived from price,
        # so no price change means no change in graph scaling.
        if hasattr(self, "_history") and self._history and price != prev_price:
            self.update_graph(self._history)

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
        self._current_price_selected = None
        self._price_label.configure(text="—", text_color="white")
        self._trend_label.configure(text="")
        self._meta_label.configure(text="")
        self._buy_label.configure(text="—", text_color="#4a9eff")
        if hasattr(self, "_currency_label") and self._currency_label:
            self._currency_label.configure(text=symbol)

        # Redraw the graph to reflect USD fallback immediately (since selected price is None)
        if hasattr(self, "_history") and self._history:
            self.update_graph(self._history)

    def hide_graph_placeholder(self):
        self._graph_placeholder.place_forget()

    def update_graph(self, history: list):
        """
        Embed or refresh the price history chart.
        history: list of [date_str, price_usd, volume] from Steam line1.
        Must be called from the main thread.
        """
        self._history = history

        if self._mpl_canvas is None:
            self._create_graph()

        self._ax.clear()
        self._ax.set_facecolor(_GRAPH_BG)

        if not hasattr(self, "_ax2"):
            self._ax2 = self._ax.twinx()
        else:
            self._ax2.clear()

        self._ax2.set_facecolor("none")
        for spine in self._ax2.spines.values():
            spine.set_visible(False)
        self._ax2.set_xticks([])
        self._ax2.set_yticks([])

        # Calculate exchange rate from USD to target currency if active price exists
        exchange_rate = 1.0
        graph_currency_symbol = "$"
        if self._current_price_selected is not None and history:
            last_hist_price = history[-1][1]
            if last_hist_price > 0:
                exchange_rate = self._current_price_selected / last_hist_price
                graph_currency_symbol = self._currency_symbol

        self._exchange_rate = exchange_rate
        self._graph_currency_symbol = graph_currency_symbol

        # Filter history by selected range
        def parse_date(d_str):
            try:
                return datetime.strptime(d_str, "%b %d %Y %H:%M:%S +00").replace(tzinfo=timezone.utc)
            except Exception:
                return None

        filtered = history
        if history and self._active_range != "Lifetime":
            now = datetime.now(timezone.utc)
            if self._active_range == "Week":
                cutoff = now - timedelta(days=7)
            elif self._active_range == "Month":
                cutoff = now - timedelta(days=30)
            elif self._active_range == "Year":
                cutoff = now - timedelta(days=365)
            else:
                cutoff = None

            if cutoff:
                filtered = [row for row in history if (parse_date(row[0]) or now) >= cutoff]
                # If filter results in too few points, fallback to all to avoid empty chart
                if len(filtered) < 2:
                    filtered = history

        self._plotted_data = filtered

        if filtered:
            prices = [row[1] * exchange_rate for row in filtered]
            volumes = [row[2] if row[2] is not None else 0 for row in filtered]

            # 1. Plot volume bars (blue, transparency, squashed to bottom 25%)
            self._ax2.bar(range(len(volumes)), volumes, color="#478cbd", alpha=0.3, width=0.8)
            max_vol = max(volumes) if volumes and any(volumes) else 1
            self._ax2.set_ylim(0, max_vol * 4)

            # 2. Plot price line (green color matching Steam, with shaded area)
            self._ax.plot(range(len(prices)), prices, color="#A5C33A", linewidth=1.2, antialiased=False)
            self._ax.fill_between(range(len(prices)), prices, color="#A5C33A", alpha=0.12)
            self._ax.margins(x=0.01, y=0.15)

            # 3. Style Y axis (price labels in selected currency on the left)
            self._ax.yaxis.tick_left()
            self._ax.tick_params(axis='y', colors='gray', labelsize=6.5, length=2, pad=2)
            def y_fmt(val, pos):
                return f"{graph_currency_symbol}{val:,.0f}"
            self._ax.yaxis.set_major_formatter(FuncFormatter(y_fmt))

            # 4. Style X axis (dates at the bottom)
            if len(prices) > 1:
                tick_indices = [0, len(prices) // 2, len(prices) - 1]
                tick_labels = []
                for idx in tick_indices:
                    date_str = filtered[idx][0]
                    try:
                        dt = datetime.strptime(date_str, "%b %d %Y %H:%M:%S +00")
                        tick_labels.append(dt.strftime("%d/%m"))
                    except Exception:
                        tick_labels.append(date_str[:6])
                self._ax.set_xticks(tick_indices)
                self._ax.set_xticklabels(tick_labels, color='gray', fontsize=6.5)
                self._ax.tick_params(axis='x', colors='gray', labelsize=6.5, length=2, pad=2)
            else:
                self._ax.set_xticks([])
                self._ax.set_xticklabels([])

            # 5. Enable grid lines behind plot
            self._ax.grid(True, which='both', axis='both', color='#2d2d2d', linestyle='-', linewidth=0.5)
            self._ax.set_axisbelow(True)

            # 6. Create hover visual elements
            self._hover_vline = self._ax.axvline(x=0, color="#ffffff", linestyle="--", linewidth=0.8, visible=False)
            self._hover_point = self._ax.plot([], [], 'o', color='#A5C33A', markersize=4, visible=False)[0]
            self._tooltip = self._ax.annotate(
                "",
                xy=(0, 0),
                xycoords=('data', 'axes fraction'),
                xytext=(10, 0),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.5", fc="#2a2a2a", ec="gray", lw=0.5, alpha=0.95),
                fontsize=7.5,
                color="white",
                visible=False,
            )
        else:
            self._ax.text(
                0.5, 0.5, "No history data",
                ha="center", va="center",
                transform=self._ax.transAxes,
                color="gray", fontsize=7,
            )
            self._ax.set_xticks([])
            self._ax.set_yticks([])

        for spine in self._ax.spines.values():
            spine.set_visible(False)
        self._mpl_canvas.draw_idle()

        # Lift controls to make sure they are not covered by the canvas
        self._filter_frame.lift()
        if hasattr(self, "_currency_label") and self._currency_label:
            self._currency_label.configure(text=graph_currency_symbol)
            self._currency_label.lift()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _create_graph(self):
        """Build the matplotlib figure and embed it in the graph slot frame."""
        self._fig = Figure(figsize=(5, 0.9), dpi=80, facecolor=_GRAPH_BG)
        # Allocate space for labels, leaving top 24% empty for filter buttons
        self._fig.subplots_adjust(left=0.08, right=0.97, top=0.76, bottom=0.18)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor(_GRAPH_BG)

        self._mpl_canvas = FigureCanvasTkAgg(self._fig, master=self._graph_slot)
        self._mpl_canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.hide_graph_placeholder()

        # Lift controls above canvas
        self._filter_frame.lift()
        if hasattr(self, "_currency_label") and self._currency_label:
            self._currency_label.lift()

        # Bind hover events
        self._fig.canvas.mpl_connect("motion_notify_event", self._on_hover)
        self._fig.canvas.mpl_connect("axes_leave_event", self._on_leave)

    def _on_hover(self, event):
        if not hasattr(self, "_plotted_data") or not self._plotted_data:
            self._hide_hover_elements()
            return

        if event.inaxes not in [self._ax, getattr(self, "_ax2", None)]:
            self._hide_hover_elements()
            return

        x = event.xdata
        if x is None:
            self._hide_hover_elements()
            return

        idx = int(round(x))
        if idx < 0 or idx >= len(self._plotted_data):
            self._hide_hover_elements()
            return

        # Fetch datapoint values
        date_str, price, volume = self._plotted_data[idx]
        volume_val = volume if volume is not None else 0

        # Get active scaling parameters
        exchange_rate = getattr(self, "_exchange_rate", 1.0)
        graph_currency_symbol = getattr(self, "_graph_currency_symbol", "$")
        price_converted = price * exchange_rate

        # Format price based on currency type (no decimals for Rp, ₩, ₫, ¥)
        is_integer_currency = graph_currency_symbol in ["Rp", "₫", "₩", "¥"]
        if is_integer_currency:
            price_str = f"{price_converted:,.0f}"
        else:
            price_str = f"{price_converted:,.2f}"

        # Format datetime to a user-friendly format (English)
        try:
            dt = datetime.strptime(date_str, "%b %d %Y %H:%M:%S +00")
            formatted_date = dt.strftime("%A, %b %d, %Y")
        except Exception:
            formatted_date = date_str

        text = f"{formatted_date}\nMedian Price: {graph_currency_symbol} {price_str}\nVolume: {volume_val:,}"

        # Update vertical cursor line
        if hasattr(self, "_hover_vline"):
            self._hover_vline.set_xdata([idx, idx])
            self._hover_vline.set_visible(True)

        # Update hover dot on price curve
        if hasattr(self, "_hover_point"):
            self._hover_point.set_data([idx], [price_converted])
            self._hover_point.set_visible(True)

        # Update tooltip location and content
        if hasattr(self, "_tooltip"):
            self._tooltip.xy = (idx, 0.45)
            self._tooltip.set_text(text)
            self._tooltip.set_visible(True)

            # Prevent clipping and overlapping with the top-right range buttons
            if idx > len(self._plotted_data) * 0.5:
                self._tooltip.set_horizontalalignment('right')
                self._tooltip.set_verticalalignment('center')
                self._tooltip.set_position((-12, 0))
            else:
                self._tooltip.set_horizontalalignment('left')
                self._tooltip.set_verticalalignment('center')
                self._tooltip.set_position((12, 0))

        self._mpl_canvas.draw_idle()

    def _on_leave(self, event):
        self._hide_hover_elements()

    def _hide_hover_elements(self):
        updated = False
        if hasattr(self, "_hover_vline") and self._hover_vline.get_visible():
            self._hover_vline.set_visible(False)
            updated = True
        if hasattr(self, "_hover_point") and self._hover_point.get_visible():
            self._hover_point.set_visible(False)
            updated = True
        if hasattr(self, "_tooltip") and self._tooltip.get_visible():
            self._tooltip.set_visible(False)
            updated = True

        if updated and self._mpl_canvas:
            self._mpl_canvas.draw_idle()

    def _on_range_change(self, range_name: str):
        if self._active_range == range_name:
            return
        self._active_range = range_name
        self._update_filter_buttons_ui()
        if hasattr(self, "_history") and self._history:
            self.update_graph(self._history)

    def _update_filter_buttons_ui(self):
        for name, btn in self._filter_buttons.items():
            if name == self._active_range:
                btn.configure(fg_color=("#2d2d2d", "#2d2d2d"), text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color="gray65")

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

    def cleanup(self):
        """Close the matplotlib figure, removing it from the global figure registry."""
        if self._fig is not None:
            from matplotlib import pyplot as plt
            plt.close(self._fig)
            self._fig = None

    def _handle_delete(self):
        if self._on_delete:
            self._on_delete(self._item_name)
