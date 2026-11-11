"""Futures contract helpers: expiries, front-month selection, position wording."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import TypeVar

T = TypeVar("T")

MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M", 7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
QUARTER_MONTHS = (3, 6, 9, 12)


def third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7  # Friday is weekday 4
    return first + timedelta(days=offset + 14)


def quarterly_expiries(start: date, count: int = 4) -> list[date]:
    """Next `count` quarterly equity-index expiries on/after `start` (3rd Friday of Mar/Jun/Sep/Dec)."""
    out: list[date] = []
    year = start.year
    while len(out) < count:
        for m in QUARTER_MONTHS:
            d = third_friday(year, m)
            if d >= start:
                out.append(d)
                if len(out) == count:
                    break
        year += 1
    return out


def local_symbol(symbol: str, expiry: date) -> str:
    """e.g. ('ES', 2026-12-18) -> 'ESZ6' (IB's local symbol style)."""
    return f"{symbol}{MONTH_CODES[expiry.month]}{expiry.year % 10}"


def choose_front_month(candidates: Iterable[tuple[date, T]], today: date, roll_days: int) -> tuple[date, T]:
    """Earliest contract that is more than `roll_days` days from expiry.

    Equity-index volume moves to the next quarter roughly 8 days before expiry,
    so by default we switch then too instead of trading a dying contract.
    """
    live = sorted((c for c in candidates if (c[0] - today).days > roll_days), key=lambda c: c[0])
    if not live:
        raise LookupError("No contract found outside the roll window")
    return live[0]


def describe_position(qty: int) -> str:
    if qty == 0:
        return "flat"
    return f"long {qty}" if qty > 0 else f"short {abs(qty)}"
