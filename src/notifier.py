import os
import logging
import requests

from . import config as _cfg

log = logging.getLogger(__name__)

_EMBED_COLOR = 0xFFA500  # orange — attention-grabbing alert color


def send_alert(item_name: str, current_price: float, alert_price: float) -> None:
    """
    POST a Discord embed alert when an item's price crosses at or below alert_price.

    Reads DISCORD_WEBHOOK_URL from environment (.env loaded by main.py).
    Failure is logged but never propagated — must not crash the monitoring loop.
    """
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        log.debug("DISCORD_WEBHOOK_URL not set — alert skipped.")
        return

    sym = _cfg.get_currency_symbol()
    payload = {
        "embeds": [
            {
                "title": "\U0001f514 Price Alert — TBH Market Tracker",
                "color": _EMBED_COLOR,
                "fields": [
                    {
                        "name": "Item",
                        "value": item_name,
                        "inline": False,
                    },
                    {
                        "name": "Current Price",
                        "value": f"{sym} {current_price:,.0f}",
                        "inline": True,
                    },
                    {
                        "name": "Alert Threshold",
                        "value": f"{sym} {alert_price:,.0f}",
                        "inline": True,
                    },
                ],
                "footer": {"text": "TBH Market Tracker"},
            }
        ]
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        log.info(
            "Alert sent: %s — Rp %,.0f at or below threshold Rp %,.0f.",
            item_name, current_price, alert_price,
        )
    except Exception as exc:
        log.warning("Discord alert failed for %s: %s", item_name, exc)
