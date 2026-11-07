"""Simulated broker: fake fills, real position math. For testing without TWS."""

from __future__ import annotations

import asyncio
import itertools
import random
from datetime import date, datetime

from ..config import Instrument
from ..contracts import choose_front_month, local_symbol, quarterly_expiries
from ..risk import ET
from .base import Broker, ContractRef, OrderResult


class SimBroker(Broker):
    name = "sim"

    def __init__(self, start_price: float = 6000.0, fill_delay_s: float = 0.05, today: date | None = None, seed=None):
        self._connected = False
        self._positions: dict[str, tuple[ContractRef, int]] = {}
        self._price: dict[str, float] = {}
        self._start_price = start_price
        self._delay = fill_delay_s
        self._today = today
        self._ids = itertools.count(1)
        self._rng = random.Random(seed)
        # order_id -> (root symbol, placed by this app?). Lets tests model orders entered in TWS.
        self.working: dict[str, tuple[str, bool]] = {}
        self.reject_next: str | None = None  # set to a message to make the next order fail
        self.raise_next: Exception | None = None  # make the next order raise (e.g. a dropped connection)
        self.silent_fill_next = False  # report "Timeout" but actually fill (late fill after cancel)

    async def connect(self) -> str:
        self._connected = True
        return "SIM-PAPER"

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _today_date(self) -> date:
        return self._today or datetime.now(ET).date()

    async def front_month(self, inst: Instrument, roll_days: int) -> ContractRef:
        today = self._today_date()
        expiries = [(d, d) for d in quarterly_expiries(today, 3)]
        exp, _ = choose_front_month(expiries, today, roll_days)
        return ContractRef(inst.symbol, local_symbol(inst.symbol, exp), exp)

    async def position(self, contract: ContractRef) -> int:
        entry = self._positions.get(contract.local_symbol)
        return entry[1] if entry else 0

    async def positions(self, symbols: set[str]) -> list[tuple[ContractRef, int]]:
        return [(c, q) for c, q in self._positions.values() if c.symbol in symbols and q != 0]

    def set_position(self, contract: ContractRef, qty: int) -> None:
        """Test helper."""
        self._positions[contract.local_symbol] = (contract, qty)

    def _tick(self, symbol: str) -> float:
        p = self._price.get(symbol, self._start_price)
        p = max(1.0, p + self._rng.choice((-1, 0, 1)) * 0.25)
        self._price[symbol] = p
        return p

    async def market_order(self, contract: ContractRef, action: str, quantity: int) -> OrderResult:
        oid = f"SIM{next(self._ids)}"
        await asyncio.sleep(self._delay)
        if self.raise_next:
            err, self.raise_next = self.raise_next, None
            raise err
        if self.reject_next:
            msg, self.reject_next = self.reject_next, None
            return OrderResult(oid, action, quantity, "Rejected", 0, None, msg)
        price = self._tick(contract.symbol)
        signed = quantity if action == "BUY" else -quantity
        current = await self.position(contract)
        self._positions[contract.local_symbol] = (contract, current + signed)
        if self.silent_fill_next:
            self.silent_fill_next = False
            return OrderResult(oid, action, quantity, "Timeout", 0, None, "Not filled within 10s; cancel sent.")
        return OrderResult(oid, action, quantity, "Filled", quantity, price)

    async def cancel_open_orders(self, symbols: set[str], global_cancel: bool = False) -> int:
        if global_cancel:
            doomed = list(self.working)
        else:
            doomed = [oid for oid, (sym, ours) in self.working.items() if sym in symbols and ours]
        for oid in doomed:
            del self.working[oid]
        return len(doomed)

    async def open_orders(self, symbols: set[str]) -> int:
        return sum(1 for sym, _ in self.working.values() if sym in symbols)
