"""Interactive Brokers adapter (TWS or IB Gateway) built on ib_async."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Awaitable, Callable, TypeVar

from ib_async import IB, Contract, Future, MarketOrder

from ..config import BrokerConfig, Instrument
from ..contracts import choose_front_month
from ..risk import ET
from .base import Broker, BrokerError, ContractRef, OrderResult
from .ibkr_messages import plain_from_raw, plain_reason

T = TypeVar("T")

# Informational "farm connection is OK" style codes that aren't real errors.
INFO_CODES = {2104, 2106, 2107, 2108, 2119, 2158, 2100, 2150}
REQUEST_TIMEOUT_S = 10.0  # no request to TWS may hang the app longer than this
CANCEL_WAIT_S = 3.0


def _parse_expiry(s: str) -> date | None:
    s = (s or "")[:8]
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


class IBKRBroker(Broker):
    name = "ibkr"

    def __init__(self, cfg: BrokerConfig, allow_live: bool = False, on_event: Callable[[str, dict], None] | None = None):
        self.cfg = cfg
        self.allow_live = allow_live
        self.ib = IB()
        self.account = ""
        self._synced = False  # True only once positions/orders have been loaded after a (re)connect
        self._on_event = on_event or (lambda kind, data: None)
        self.ib.errorEvent += self._on_error
        self.ib.disconnectedEvent += self._on_disconnect

    # ---- connection -------------------------------------------------------------------------

    async def connect(self) -> str:
        c = self.cfg
        self._synced = False
        try:
            # connectAsync returns only after positions, open orders and executions are loaded.
            await self.ib.connectAsync(c.host, c.port, clientId=c.client_id, timeout=REQUEST_TIMEOUT_S, account=c.account)
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError, ConnectionError) as e:
            self.ib.disconnect()
            raise BrokerError(
                f"Couldn't reach TWS/IB Gateway at {c.host}:{c.port} ({e.__class__.__name__}). "
                "Is it running and logged in, with API socket clients enabled on that port?"
            ) from e

        accounts = self.ib.managedAccounts()
        if not accounts:
            self.ib.disconnect()
            raise BrokerError("Connected, but IBKR reported no accounts.")
        if c.account and c.account not in accounts:
            self.ib.disconnect()
            raise BrokerError(f"Account {c.account} isn't on this login. Available: {', '.join(accounts)}")
        self.account = c.account or accounts[0]

        # IBKR paper accounts start with "D" (e.g. DU1234567). Refuse any mismatch.
        is_paper = self.account.upper().startswith("D")
        if c.trading_mode == "paper" and not is_paper:
            self.ib.disconnect()
            raise BrokerError(
                f"trading_mode is 'paper' but account {self.account} looks LIVE. Refusing to trade. "
                "Log TWS/Gateway into the paper account."
            )
        if c.trading_mode == "live":
            if is_paper:
                self.ib.disconnect()
                raise BrokerError(f"trading_mode is 'live' but account {self.account} is a paper account.")
            if not self.allow_live:
                self.ib.disconnect()
                raise BrokerError("Live trading needs the --live flag as well as trading_mode = 'live'.")
        self._synced = True
        return self.account

    async def disconnect(self) -> None:
        self._synced = False
        if self.ib.isConnected():
            self.ib.disconnect()

    @property
    def connected(self) -> bool:
        return self._synced and self.ib.isConnected()

    def _on_disconnect(self) -> None:
        self._synced = False  # positions are cleared on disconnect; never trade on them
        self._on_event("disconnected", {})

    def _on_error(self, *args) -> None:
        # ib_async emits (reqId, errorCode, errorString, contract)
        req_id, code, msg = (list(args) + [None, None, None])[:3]
        if code in INFO_CODES:
            return
        self._on_event("broker_error", {"req_id": req_id, "code": code, "message": plain_reason(code, msg or ""),
                                        "raw": msg})

    async def _call(self, what: str, aw: Awaitable[T]) -> T:
        """Every request to TWS gets a timeout, and library errors become BrokerError."""
        try:
            return await asyncio.wait_for(aw, REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError as e:
            raise BrokerError(f"IBKR didn't answer the {what} request within {REQUEST_TIMEOUT_S:g}s.") from e
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"{what} failed: {e}") from e

    def _require_connection(self) -> None:
        if not self.connected:
            raise BrokerError("Not connected to IBKR.")

    # ---- contracts ----------------------------------------------------------------------------

    async def front_month(self, inst: Instrument, roll_days: int) -> ContractRef:
        self._require_connection()
        query = Future(symbol=inst.symbol, exchange=inst.exchange, currency=inst.currency)
        details = await self._call("contract details", self.ib.reqContractDetailsAsync(query))
        candidates = []
        for d in details:
            k = d.contract
            if k is None or k.secType != "FUT" or k.symbol != inst.symbol:
                continue
            if k.tradingClass and k.tradingClass != inst.symbol:
                continue
            exp = _parse_expiry(k.lastTradeDateOrContractMonth)
            if exp:
                candidates.append((exp, k))
        if not candidates:
            raise BrokerError(
                f"IBKR returned no {inst.symbol} futures on {inst.exchange}. "
                "Check the account has futures trading permissions."
            )
        today = datetime.now(ET).date()
        exp, k = choose_front_month(candidates, today, roll_days)
        return ContractRef(inst.symbol, k.localSymbol, exp, raw=k)

    async def _tradable(self, raw: Contract) -> Contract:
        """Position contracts come back without an exchange; re-qualify by conId."""
        if raw.exchange:
            return raw
        qualified = await self._call("contract lookup", self.ib.qualifyContractsAsync(Contract(conId=raw.conId)))
        if not qualified or not qualified[0]:
            raise BrokerError(f"Couldn't qualify contract {raw.localSymbol}")
        return qualified[0]

    # ---- positions ---------------------------------------------------------------------------

    async def position(self, contract: ContractRef) -> int:
        self._require_connection()
        con_id = contract.raw.conId
        return int(sum(p.position for p in self.ib.positions(self.account) if p.contract.conId == con_id))

    async def positions(self, symbols: set[str]) -> list[tuple[ContractRef, int]]:
        self._require_connection()
        out = []
        for p in self.ib.positions(self.account):
            k = p.contract
            if k.secType == "FUT" and k.symbol in symbols and p.position:
                exp = _parse_expiry(k.lastTradeDateOrContractMonth)
                out.append((ContractRef(k.symbol, k.localSymbol, exp, raw=k), int(p.position)))
        return out

    def avg_price(self, contract: ContractRef) -> float | None:
        if not self.connected or contract.raw is None:
            return None
        for p in self.ib.positions(self.account):
            if p.contract.conId == contract.raw.conId and p.position:
                try:
                    mult = float(p.contract.multiplier or contract.raw.multiplier or 1)
                except ValueError:
                    mult = 1.0
                return p.avgCost / mult if mult else None
        return None

    def working_count(self, symbols: set[str]) -> int | None:
        if not self.connected:
            return None
        return len(self._working(symbols))

    # ---- orders ------------------------------------------------------------------------------

    async def market_order(self, contract: ContractRef, action: str, quantity: int) -> OrderResult:
        self._require_connection()
        k = await self._tradable(contract.raw)
        order = MarketOrder(action, quantity, account=self.account, tif="DAY")
        try:
            trade = self.ib.placeOrder(k, order)
        except Exception as e:  # nothing was sent
            raise BrokerError(f"Order not sent: {e}") from e

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.cfg.order_timeout_s
        while not trade.isDone() and loop.time() < deadline and self.ib.isConnected():
            await asyncio.sleep(0.01)

        oid = str(trade.order.orderId)
        if not self.ib.isConnected() and not trade.isDone():
            return OrderResult(oid, action, quantity, "Unknown", int(trade.orderStatus.filled or 0), None,
                               "Lost connection while the order was working. Its state is unknown.")

        timed_out = not trade.isDone()
        if timed_out:
            try:
                self.ib.cancelOrder(trade.order)
            except Exception:
                pass
            end = loop.time() + CANCEL_WAIT_S
            while not trade.isDone() and loop.time() < end and self.ib.isConnected():
                await asyncio.sleep(0.02)

        st = trade.orderStatus
        errors = [e.message for e in trade.log if e.errorCode and e.errorCode not in INFO_CODES]
        message = plain_from_raw(errors[-1]) if errors else ""
        status = st.status
        if timed_out and status != "Filled":
            if trade.isDone():
                status = "Timeout"
                message = message or f"Not filled within {self.cfg.order_timeout_s:g}s. Cancelled."
            else:
                status = "Unknown"
                message = "Not filled in time and the cancel isn't confirmed. It may still be working."
        return OrderResult(
            order_id=oid,
            action=action,
            quantity=quantity,
            status=status,
            filled=int(st.filled or 0),
            avg_price=st.avgFillPrice or None,
            message=message,
        )

    def _working(self, symbols: set[str]):
        return [
            t for t in self.ib.openTrades()
            if t.contract.secType == "FUT" and t.contract.symbol in symbols and not t.isDone()
        ]

    async def cancel_open_orders(self, symbols: set[str], global_cancel: bool = False) -> int:
        self._require_connection()
        await self._call("open orders", self.ib.reqAllOpenOrdersAsync())
        if global_cancel:
            n = len(self._working(symbols))
            try:
                self.ib.reqGlobalCancel()  # every open order in the account, any symbol, any source
            except Exception as e:
                raise BrokerError(f"Global cancel failed: {e}") from e
            return n
        # The API can only cancel orders placed by this same client id.
        n = 0
        for t in self._working(symbols):
            if t.order.clientId == self.cfg.client_id and t.order.orderId > 0:
                try:
                    self.ib.cancelOrder(t.order)
                    n += 1
                except Exception as e:
                    raise BrokerError(f"Cancel failed: {e}") from e
        return n

    async def open_orders(self, symbols: set[str]) -> int:
        self._require_connection()
        trades = await self._call("open orders", self.ib.reqAllOpenOrdersAsync())
        # TWS's fresh answer, not the local cache: a manual order cancelled in TWS never sends
        # this client a status update, so the cache would keep counting it.
        seen = {}
        for t in trades or []:
            k = t.contract
            if k.secType == "FUT" and k.symbol in symbols and not t.isDone():
                seen[getattr(t.order, "permId", 0) or id(t)] = t
        return len(seen)
