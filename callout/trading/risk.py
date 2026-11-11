"""Pre-trade checks: position limit, order pace and market hours. Every order passes through here."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..config import Config
from .market_hours import ET, cme_equity_index_open


@dataclass
class RiskDecision:
    ok: bool
    reason: str = ""


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
