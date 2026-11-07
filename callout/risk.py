"""Pre-trade checks. Every order goes through here before reaching the broker."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Callable
from zoneinfo import ZoneInfo

from .config import Config

ET = ZoneInfo("America/New_York")


@dataclass
class RiskDecision:
    ok: bool
    reason: str = ""


def cme_equity_index_open(now: datetime) -> bool:
    """CME Globex equity-index futures (ES/MES): Sun 6pm -> Fri 5pm ET, daily halt 5-6pm ET.

    Exchange holidays aren't modelled; the broker rejects orders on those days anyway.
    """
    t = now.astimezone(ET)
    wd, hm = t.weekday(), t.time()
    five, six = dtime(17, 0), dtime(18, 0)
    if wd == 5:  # Saturday
        return False
    if wd == 6:  # Sunday
        return hm >= six
    if wd == 4:  # Friday
        return hm < five
    return not (five <= hm < six)  # Mon-Thu daily maintenance halt


def market_clock(now: datetime) -> tuple[bool, datetime]:
    """(open now?, when that next changes) for CME equity-index futures, in ET."""
    from datetime import timedelta

    t = now.astimezone(ET)
    is_open = cme_equity_index_open(t)
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    at = lambda d, h: (day + timedelta(days=d)).replace(hour=h)  # noqa: E731
    wd, h = t.weekday(), t.hour + t.minute / 60
    if is_open:
        if wd == 6 or h >= 18:  # evening session: closes tomorrow 5pm
            return True, at(1, 17)
        return True, at(0, 17)
    if wd <= 3 and 17 <= h < 18:  # daily halt
        return False, at(0, 18)
    days_to_sunday = (6 - wd) % 7
    return False, at(days_to_sunday, 18)


def market_status_text(now: datetime) -> tuple[bool, str]:
    is_open, change = market_clock(now)
    t = now.astimezone(ET)
    when = change.strftime("%I:%M %p").lstrip("0")
    if change.date() != t.date():
        when = change.strftime("%a ") + when
    return is_open, ("Market open · closes " if is_open else "Market closed · opens ") + when + " ET"


class RiskManager:
    def __init__(
        self,
        cfg: Config,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(ET),
    ):
        self.cfg = cfg
        self._mono = monotonic
        self._now = now
        self._recent: deque[float] = deque()
        self._last_order: float | None = None
        self.ignore_market_hours = False

    def market_open(self) -> bool:
        return self.ignore_market_hours or not self.cfg.safety.check_market_hours or cme_equity_index_open(self._now())

    def check_order(self, symbol: str, current: int, resulting: int) -> RiskDecision:
        s = self.cfg.safety
        if not self.market_open():
            return RiskDecision(False, "Market is closed.")
        limit = self.cfg.max_position_for(symbol)
        # Allow anything that shrinks exposure even if the account is somehow over the limit.
        if abs(resulting) > limit and abs(resulting) >= abs(current):
            return RiskDecision(False, f"That would put you at {abs(resulting)} contracts. Max is {limit}.")
        now = self._mono()
        if self._last_order is not None and now - self._last_order < s.min_seconds_between_orders:
            return RiskDecision(False, "Too fast. Wait a second and say it again.")
        self._trim(now)
        if len(self._recent) >= s.max_orders_per_minute:
            return RiskDecision(False, f"Rate limit: {s.max_orders_per_minute} orders a minute.")
        return RiskDecision(True)

    def check_flatten(self) -> RiskDecision:
        # Flatten skips position, speed and rate limits: it only ever reduces risk.
        if not self.market_open():
            return RiskDecision(False, "Market is closed. Nothing sent.")
        return RiskDecision(True)

    def record_order(self) -> None:
        now = self._mono()
        self._last_order = now
        self._recent.append(now)

    def _trim(self, now: float) -> None:
        while self._recent and now - self._recent[0] > 60:
            self._recent.popleft()
