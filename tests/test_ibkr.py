"""IBKR adapter tests against a fake IB connection (no TWS needed)."""

import asyncio
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pytest

pytest.importorskip("ib_async")

from ib_async import Contract  # noqa: E402

from callout.brokers.base import BrokerError  # noqa: E402
from callout.brokers.ibkr import IBKRBroker  # noqa: E402
from callout.config import BrokerConfig, Instrument  # noqa: E402


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self


@dataclass
class FakeTrade:
    order: object
    contract: object
    orderStatus: object
    log: list = field(default_factory=list)
    done: bool = True

    def isDone(self):
        return self.done


def fut(symbol, month, con_id, exchange="CME"):
    c = Contract(secType="FUT", symbol=symbol, lastTradeDateOrContractMonth=month, conId=con_id,
                 exchange=exchange, tradingClass=symbol, currency="USD")
    c.localSymbol = {"20261218": f"{symbol}Z6", "20270319": f"{symbol}H7", "20260918": f"{symbol}U6"}[month]
    return c


class FakeIB:
    def __init__(self, accounts=("DU1234567",), fill=True):
        self.errorEvent = Event()
        self.disconnectedEvent = Event()
        self._accounts = list(accounts)
        self._connected = False
        self._positions = []
        self.placed = []
        self.cancelled = []
        self.fill = fill
        self.cancel_confirms = True
        self.trades = []
        self.open = []  # FakeTrades still working (for flatten tests)

    async def connectAsync(self, *a, **k):
        self._connected = True

    def isConnected(self):
        return self._connected

    def disconnect(self):
        self._connected = False

    def managedAccounts(self):
        return self._accounts

    async def reqContractDetailsAsync(self, query):
        return [SimpleNamespace(contract=fut(query.symbol, m, i)) for i, m in
                ((1, "20261218"), (2, "20270319"))]

    async def qualifyContractsAsync(self, c):
        return [fut("ES", "20260918", c.conId)]

    def positions(self, account=""):
        return self._positions

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        status = SimpleNamespace(status="Filled" if self.fill else "Submitted", filled=order.totalQuantity if self.fill else 0,
                                 avgFillPrice=6001.25 if self.fill else 0.0)
        order.orderId = len(self.placed)
        t = FakeTrade(order, contract, status, done=self.fill)
        self.trades.append(t)
        return t

    def cancelOrder(self, order):
        self.cancelled.append(order)
        if self.cancel_confirms:
            for t in self.trades:
                if t.order is order:
                    t.done = True
                    t.orderStatus.status = "Cancelled"

    async def reqAllOpenOrdersAsync(self):
        return []

    def openTrades(self):
        return [t for t in self.open if not t.done]

    def reqGlobalCancel(self):
        for t in self.open:
            t.done = True


def broker(mode="paper", accounts=("DU1234567",), allow_live=False, fill=True, timeout=0.1):
    port = 7497 if mode == "paper" else 7496
    b = IBKRBroker(BrokerConfig(port=port, trading_mode=mode, order_timeout_s=timeout), allow_live=allow_live)
    b.ib = FakeIB(accounts, fill)
    return b


def run(coro):
    return asyncio.run(coro)


def test_paper_mode_refuses_live_account():
    b = broker("paper", accounts=("U7654321",))
    with pytest.raises(BrokerError, match="looks LIVE"):
        run(b.connect())
    assert not b.connected


def test_live_mode_needs_flag_and_live_account():
    with pytest.raises(BrokerError, match="--live"):
        run(broker("live", accounts=("U7654321",)).connect())
    with pytest.raises(BrokerError, match="paper account"):
        run(broker("live", accounts=("DU1",), allow_live=True).connect())
    assert run(broker("live", accounts=("U7654321",), allow_live=True).connect()) == "U7654321"


def test_front_month_and_order_fill(monkeypatch):
    import callout.brokers.ibkr as mod

    class FakeDT:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2026, 11, 9, 10, tzinfo=tz)

        strptime = staticmethod(__import__("datetime").datetime.strptime)

    monkeypatch.setattr(mod, "datetime", FakeDT)
    b = broker()
    run(b.connect())
    c = run(b.front_month(Instrument("ES", spoken=["es"]), 8))
    assert c.local_symbol == "ESZ6" and c.expiry == date(2026, 12, 18)
    r = run(b.market_order(c, "BUY", 1))
    assert r.fully_filled and r.avg_price == 6001.25
    placed_contract, order = b.ib.placed[0]
    assert order.action == "BUY" and order.totalQuantity == 1 and order.orderType == "MKT"
    assert order.account == "DU1234567"


def test_unfilled_order_times_out_and_is_cancelled():
    b = broker(fill=False, timeout=0.05)
    run(b.connect())
    k = fut("ES", "20261218", 1)
    from callout.brokers.base import ContractRef

    r = run(b.market_order(ContractRef("ES", "ESZ6", date(2026, 12, 18), raw=k), "SELL", 1))
    assert r.status == "Timeout" and not r.fully_filled
    assert len(b.ib.cancelled) == 1


def test_unconfirmed_cancel_reports_unknown(monkeypatch):
    import callout.brokers.ibkr as mod

    monkeypatch.setattr(mod, "CANCEL_WAIT_S", 0.05)
    b = broker(fill=False, timeout=0.05)
    b.ib.cancel_confirms = False
    run(b.connect())
    from callout.brokers.base import ContractRef

    r = run(b.market_order(ContractRef("ES", "ESZ6", date(2026, 12, 18), raw=fut("ES", "20261218", 1)), "BUY", 1))
    assert r.status == "Unknown" and "may still be working" in r.message


def test_not_connected_until_synced_and_after_disconnect():
    b = broker()
    assert not b.connected
    run(b.connect())
    assert b.connected
    b._on_disconnect()
    assert not b.connected
    with pytest.raises(BrokerError):
        run(b.positions({"ES"}))


def test_place_order_failure_becomes_broker_error():
    b = broker()
    run(b.connect())

    def boom(*a):
        raise ConnectionError("Not connected")

    b.ib.placeOrder = boom
    from callout.brokers.base import ContractRef

    with pytest.raises(BrokerError, match="Order not sent"):
        run(b.market_order(ContractRef("ES", "ESZ6", None, raw=fut("ES", "20261218", 1)), "BUY", 1))


def _working(order_client, order_id):
    o = SimpleNamespace(clientId=order_client, orderId=order_id)
    return FakeTrade(o, fut("ES", "20261218", 1), SimpleNamespace(status="Submitted"), done=False)


def test_cancel_only_touches_own_orders_unless_global():
    b = broker()
    run(b.connect())
    mine, manual = _working(17, 5), _working(0, 0)
    b.ib.open = [mine, manual]
    assert run(b.cancel_open_orders({"ES"})) == 1
    assert b.ib.cancelled == [mine.order]
    assert run(b.open_orders({"ES"})) == 2  # fake doesn't confirm cancels for these; both still listed
    assert run(b.cancel_open_orders({"ES"}, global_cancel=True)) == 2
    assert run(b.open_orders({"ES"})) == 0


def test_hung_request_times_out(monkeypatch):
    import callout.brokers.ibkr as mod

    monkeypatch.setattr(mod, "REQUEST_TIMEOUT_S", 0.05)
    b = broker()
    run(b.connect())

    async def hang(q):
        await asyncio.sleep(10)

    b.ib.reqContractDetailsAsync = hang
    with pytest.raises(BrokerError, match="didn't answer"):
        run(b.front_month(Instrument("ES", spoken=["es"]), 8))


def test_positions_requalify_contract_without_exchange():
    b = broker()
    run(b.connect())
    held = fut("ES", "20260918", 99, exchange="")
    b.ib._positions = [SimpleNamespace(contract=held, position=-1.0)]
    [(ref, qty)] = run(b.positions({"ES"}))
    assert qty == -1 and ref.local_symbol == "ESU6"
    r = run(b.market_order(ref, "BUY", 1))
    assert r.fully_filled
    assert b.ib.placed[0][0].exchange == "CME"  # re-qualified before ordering
