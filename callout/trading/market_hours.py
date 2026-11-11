"""When CME equity-index futures (ES, MES) trade, in US Eastern time."""

from __future__ import annotations

from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_CLOSE = dtime(17, 0)  # 5 PM ET: Friday close, and the start of the Mon-Thu daily halt
_OPEN = dtime(18, 0)  # 6 PM ET: Sunday open, and the end of the daily halt


def cme_equity_index_open(now: datetime) -> bool:
    """CME Globex equity-index futures: Sun 6 PM -> Fri 5 PM ET, with a daily 5-6 PM ET halt.

    Exchange holidays aren't modelled; the broker rejects orders on those days anyway.
    """
    t = now.astimezone(ET)
    weekday, clock = t.weekday(), t.time()
    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday
        return clock >= _OPEN
    if weekday == 4:  # Friday
        return clock < _CLOSE
    return not (_CLOSE <= clock < _OPEN)  # Mon-Thu daily halt


def market_clock(now: datetime) -> tuple[bool, datetime]:
    """(open now?, when that next changes), in ET."""
    t = now.astimezone(ET)
    is_open = cme_equity_index_open(t)
    midnight = t.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(days: int, hour: int) -> datetime:
        return (midnight + timedelta(days=days)).replace(hour=hour)

    weekday, hour = t.weekday(), t.hour + t.minute / 60
    if is_open:
        if weekday == 6 or hour >= 18:  # evening session: closes tomorrow at 5 PM
            return True, at(1, 17)
        return True, at(0, 17)
    if weekday <= 3 and 17 <= hour < 18:  # daily halt
        return False, at(0, 18)
    return False, at((6 - weekday) % 7, 18)  # weekend: opens Sunday 6 PM


def market_status_text(now: datetime) -> tuple[bool, str]:
    """(open now?, 'Market open · closes 5:00 PM ET'), for the status bar."""
    is_open, change = market_clock(now)
    when = change.strftime("%I:%M %p").lstrip("0")
    if change.date() != now.astimezone(ET).date():
        when = change.strftime("%a ") + when
    return is_open, ("Market open · closes " if is_open else "Market closed · opens ") + when + " ET"
