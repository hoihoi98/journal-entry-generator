import re
import requests
from datetime import date
from functools import lru_cache

FRANKFURTER_BASE = "https://api.frankfurter.app"

SYMBOL_TO_ISO = {
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₩": "KRW",
    "₣": "CHF",
    "₦": "NGN",
    "₱": "PHP",
    "฿": "THB",
    "₫": "VND",
}

KNOWN_ISO = {
    "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "HKD", "SGD",
    "NZD", "SEK", "NOK", "DKK", "ZAR", "INR", "MXN", "BRL", "KRW", "TWD",
    "THB", "MYR", "IDR", "PHP", "PLN", "CZK", "HUF", "TRY", "RUB", "SAR",
    "AED", "QAR", "KWD", "BHD", "OMR", "EGP", "NGN", "KES", "GHS", "VND",
    "PKR", "BDT", "LKR", "MMK", "PEN", "CLP", "COP", "ARS", "UYU",
}


def detect_foreign_currency(text: str, functional_currency: str) -> str | None:
    fc = functional_currency.upper()
    for symbol, iso in SYMBOL_TO_ISO.items():
        if symbol in text and iso != fc:
            return iso
    for match in re.finditer(r'\b([A-Z]{3})\b', text):
        code = match.group(1)
        if code in KNOWN_ISO and code != fc:
            return code
    return None


@lru_cache(maxsize=256)
def _fetch_rate(from_currency: str, to_currency: str, date_str: str) -> float | None:
    url = f"{FRANKFURTER_BASE}/{date_str}?from={from_currency}&to={to_currency}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json().get("rates", {}).get(to_currency)
    except Exception:
        return None


def get_spot_rate(from_currency: str, to_currency: str, on_date: date) -> float | None:
    return _fetch_rate(from_currency.upper(), to_currency.upper(), on_date.isoformat())


def fx_context_line(foreign: str, functional: str, rate: float, on_date: date) -> str:
    return (
        f"[FX: 1 {foreign.upper()} = {rate:.6f} {functional.upper()} "
        f"(closing spot rate {on_date.strftime('%d %b %Y')}). "
        f"Show both the {foreign.upper()} original amount and the {functional.upper()} equivalent in the journal entry.]"
    )
