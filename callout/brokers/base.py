"""The interface every broker adapter implements.

The engine only talks to this interface, so adding Tradovate, Schwab (for
stocks), etc. later means writing one new adapter and nothing else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..config import Instrument


@dataclass
class ContractRef:
    symbol: str  # root symbol, e.g. "ES"
    local_symbol: str  # e.g. "ESZ6"
    expiry: date | None
    raw: Any = field(default=None, repr=False)  # broker-native contract object

    def same_contract(self, other: "ContractRef") -> bool:
        return self.local_symbol == other.local_symbol


@dataclass
class OrderResult:
    order_id: str
    action: str  # BUY / SELL
    quantity: int
    status: str  # "Filled", "Cancelled", "Rejected", "Timeout", "Unknown" (state couldn't be confirmed)
    filled: int = 0
    avg_price: float | None = None
    message: str = ""

    @property
    def fully_filled(self) -> bool:
        return self.status == "Filled" and self.filled == self.quantity


class BrokerError(RuntimeError):
    pass


class Broker(ABC):
    name = "broker"

    @abstractmethod
    async def connect(self) -> str:
        """Connect and return the account id being traded."""

    @abstractmethod
    async def disconnect(self) -> None: ...

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    async def front_month(self, inst: Instrument, roll_days: int) -> ContractRef: ...

    @abstractmethod
    async def position(self, contract: ContractRef) -> int:
        """Net position in this exact contract (positive long, negative short)."""

    @abstractmethod
    async def positions(self, symbols: set[str]) -> list[tuple[ContractRef, int]]:
        """All non-zero positions for these root symbols, across every expiry."""

    @abstractmethod
    async def market_order(self, contract: ContractRef, action: str, quantity: int) -> OrderResult: ...

    @abstractmethod
    async def cancel_open_orders(self, symbols: set[str], global_cancel: bool = False) -> int:
        """Cancel working orders for these root symbols that this app can cancel.

        With global_cancel, use the broker's account-wide cancel instead (cancels EVERY
        open order in the account, including ones entered by hand). Returns how many
        cancels were requested.
        """

    @abstractmethod
    async def open_orders(self, symbols: set[str]) -> int:
        """How many working orders exist for these symbols, from any source."""

    # ---- display helpers (cheap, cached; used by the UI) ---------------------------------------

    def avg_price(self, contract: ContractRef) -> float | None:
        """Average entry price of the current position in this contract, if known."""
        return None

    def working_count(self, symbols: set[str]) -> int | None:
        """Working orders for these symbols from the broker's local cache, if available."""
        return None
