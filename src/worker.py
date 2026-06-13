import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, List

from .steam_api import SteamMarketAPI

log = logging.getLogger(__name__)

ITEM_DELAY = 10.0  # seconds between requests in the same worker


def seconds_until_next_hour() -> float:
    """Return seconds until the next full hour (minimum 1 second)."""
    now = datetime.now()
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max((next_hour - now).total_seconds(), 1.0)


class _BaseWorker(threading.Thread):
    """Base: daemon thread with interruptible sleep and its own SteamMarketAPI instance."""

    def __init__(self, stop_event: threading.Event):
        super().__init__(daemon=True)
        self._stop_event = stop_event
        self._api = SteamMarketAPI()

    def _sleep(self, seconds: float) -> bool:
        """
        Interruptible sleep — checks stop_event every second.
        Returns True if sleep completed normally, False if interrupted.
        """
        for _ in range(int(seconds)):
            if self._stop_event.is_set():
                return False
            time.sleep(1)
        return True


class PriceWorker(_BaseWorker):
    """
    One cycle: fetch price (priceoverview) for each item, ITEM_DELAY seconds between items.
    Thread stops automatically after one full cycle.
    MainWindow is responsible for scheduling the next cycle via self.after().

    Anti-overlap guard: check worker.is_alive() in MainWindow before starting a new cycle.
    Without the guard, a 429 backoff that extends the cycle beyond 60s causes
    cycles to pile up and worsens the rate limit situation.
    """

    def __init__(
        self,
        items: List[str],
        on_update: Callable[[str, dict], None],
        stop_event: threading.Event,
    ):
        super().__init__(stop_event)
        self._items = list(items)
        self._on_update = on_update

    def run(self):
        log.info("PriceWorker started — %d items.", len(self._items))
        for i, name in enumerate(self._items):
            if self._stop_event.is_set():
                log.info("PriceWorker stopped.")
                return

            result = self._api.get_price(name)
            log.debug("Price %-30s → %s", name, result)
            self._on_update(name, result)

            if i < len(self._items) - 1:
                if not self._sleep(ITEM_DELAY):
                    log.info("PriceWorker stopped during sleep.")
                    return

        log.info("PriceWorker finished one cycle.")


class ListingWorker(_BaseWorker):
    """
    Fetch buy/sell order data for all items via Steam's new orderbook endpoint
    (works with the market hash name directly — no item_nameid needed).
    Item metadata (color, type, icon) is sourced from item_catalog, not here.

    Price history is no longer publicly available (Steam RSC redesign 2025);
    history is always passed as an empty list.

    Callback:
      on_update(name, history, image_url, buy_orders, color_hex, item_type, item_nameid)
      buy_orders: {"highest_price": float|None, "count": int, "currency": int|None}
      history is [], the remaining metadata fields are None (sourced from catalog).
    """

    def __init__(
        self,
        items: List[str],
        on_update: Callable,
        stop_event: threading.Event,
    ):
        super().__init__(stop_event)
        self._items = list(items)
        self._on_update = on_update

    def run(self):
        log.info("ListingWorker started — %d items.", len(self._items))
        for i, name in enumerate(self._items):
            if self._stop_event.is_set():
                log.info("ListingWorker stopped.")
                return

            orderbook = self._api.get_orderbook(name)
            log.debug("Orderbook %-28s → %s", name, orderbook)

            buy_orders = {
                "highest_price": orderbook["highest_buy"],
                "count":         orderbook["buy_count"],
                "currency":      orderbook["currency"],
            }

            self._on_update(
                name,
                [],             # history: no longer publicly available
                None,           # image_url: sourced from catalog
                buy_orders,
                None,           # color_hex: sourced from catalog
                None,           # item_type: sourced from catalog
                None,           # item_nameid: dead since Steam redesign
            )

            if i < len(self._items) - 1:
                if not self._sleep(ITEM_DELAY):
                    log.info("ListingWorker stopped during sleep.")
                    return

        log.info("ListingWorker finished.")
