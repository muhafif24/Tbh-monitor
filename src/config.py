"""
Currency configuration — persisted to data/config.json.
Provides a single source of truth for the active Steam currency code + symbol.
"""
import json
import os

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "config.json",
)

# Ordered: (code, name, symbol) — shown exactly in this order in the GUI dropdown.
STEAM_CURRENCIES: list[tuple[str, str, str]] = [
    ("1",  "USD", "$"),
    ("2",  "GBP", "£"),
    ("3",  "EUR", "€"),
    ("5",  "RUB", "₽"),
    ("8",  "JPY", "¥"),
    ("9",  "NOK", "kr"),
    ("10", "IDR", "Rp"),
    ("11", "MYR", "RM"),
    ("12", "PHP", "₱"),
    ("13", "SGD", "S$"),
    ("14", "THB", "฿"),
    ("15", "VND", "₫"),
    ("16", "KRW", "₩"),
    ("17", "TRY", "₺"),
    ("20", "CAD", "C$"),
    ("21", "AUD", "A$"),
    ("23", "CNY", "¥"),
    ("24", "INR", "₹"),
    ("34", "ARS", "ARS$"),
]

# Display label → Steam currency code (used by GUI dropdown)
LABEL_TO_CODE: dict[str, str] = {
    f"{name} ({sym})": code for code, name, sym in STEAM_CURRENCIES
}

_DEFAULT_CODE = "10"  # IDR

_cache: dict = {}


def _load() -> dict:
    global _cache
    if _cache:
        return _cache
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _cache = {}
    return _cache


def _save() -> None:
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(_cache, f, indent=2)


def get_currency_code() -> str:
    return _load().get("currency_code", _DEFAULT_CODE)


def get_currency_symbol() -> str:
    code = get_currency_code()
    for c, _, sym in STEAM_CURRENCIES:
        if c == code:
            return sym
    return "Rp"


def get_currency_name() -> str:
    code = get_currency_code()
    for c, name, _ in STEAM_CURRENCIES:
        if c == code:
            return name
    return "IDR"


def get_currency_label() -> str:
    """Return the display label shown in the GUI dropdown, e.g. 'IDR (Rp)'."""
    return f"{get_currency_name()} ({get_currency_symbol()})"


def set_currency(code: str) -> None:
    cfg = _load()
    cfg["currency_code"] = code
    _save()


def get_save_path() -> str:
    """Return the saved savegame file path, or None if not set."""
    return _load().get("save_path")


def set_save_path(path: str) -> None:
    """Persist the savegame file path to configuration."""
    cfg = _load()
    cfg["save_path"] = path
    _save()

