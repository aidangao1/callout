"""The trading brain: transcript -> intent -> risk check -> confirm -> order -> readback.

Everything here is broker- and microphone-agnostic, which is what makes it
testable with the simulator and plain text.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..brokers.base import Broker, BrokerError, ContractRef, OrderResult
from ..config import Config
from ..voice.intents import Action, Intent, IntentParser
from ..voice.recognizer import Transcript
from ..voice.speaker import Speaker
from .contracts import describe_position
from .journal import Journal
from .risk import RiskManager

CHECK_PLATFORM = "Check your platform."


@dataclass
class Pending:
    intent: Intent
    current: int
    resulting: int
    created: float


@dataclass
class Meta:
    """Where a command came from and when, for the latency columns in the log."""

    source: str = "text"  # "voice" or "text"
    confidence: float | None = None
    t_release: float | None = None  # key released (monotonic)
    t_heard: float | None = None  # transcript ready (monotonic)
    extra: dict[str, Any] = field(default_factory=dict)


def _price(p: float | None) -> str:
    return "an unknown price" if p is None else f"{p:.2f}"


class Engine:
    def __init__(
        self,
        cfg: Config,
        broker: Broker,
        speaker: Speaker,
        journal: Journal,
        risk: RiskManager | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.cfg = cfg
        self.broker = broker
        self.speaker = speaker
        self.journal = journal
        self.risk = risk or RiskManager(cfg, monotonic=monotonic)
        self.parser = IntentParser(cfg)
        self.contracts: dict[str, ContractRef] = {}
        self.pending: Pending | None = None
        self.account = ""
        self._mono = monotonic
        self._lock = asyncio.Lock()  # commands, (re)connects and rolls run one at a time
        self._roll_deferred: set[str] = set()

    # ---- lifecycle ----------------------------------------------------------------------------

    async def start(self) -> str:
        """Connect (or reconnect) and pick contracts. Holds the command lock throughout."""
        async with self._lock:
            self.pending = None
            self.account = await self.broker.connect()
            await self._refresh_contracts()
            self.journal.log(
                "startup",
                broker=self.broker.name,
                account=self.account,
                mode=self.cfg.broker.trading_mode,
                contracts={s: c.local_symbol for s, c in self.contracts.items()},
                confirm=self.cfg.safety.require_confirmation,
            )
            await self._warn_about_other_expiries()
            return self.account

    async def reconfigure(self) -> None:
        """Re-read instruments and phrases from cfg (after a settings change)."""
        async with self._lock:
            self.parser = IntentParser(self.cfg)
            self.pending = None
            self.contracts = {s: c for s, c in self.contracts.items() if s in self.cfg.enabled_instruments}
            if self.broker.connected:
                await self._refresh_contracts()

    def pending_summary(self) -> dict | None:
        """What's waiting for confirm, for the screen. None when nothing is (or it has expired)."""
        p = self.pending
        if p is None:
            return None
        total = self.cfg.safety.confirm_timeout_s
        left = total - (self._mono() - p.created)
        if left <= 0:
            return None
        if p.intent.action is Action.FLATTEN:
            label = self.cfg.instruments[p.intent.symbol].symbol if p.intent.symbol else "all"
            return {
                "verb": "Flatten",
                "qty": None,
                "symbol": label,
                "from": "",
                "to": "flat",
                "left": left,
                "total": total,
            }
        inst = self.cfg.instruments[p.intent.symbol]
        return {
            "verb": "Buy" if p.intent.action is Action.BUY else "Sell",
            "qty": inst.quantity,
            "symbol": inst.symbol,
            "from": describe_position(p.current),
            "to": describe_position(p.resulting),
            "left": left,
            "total": total,
        }

    async def working_orders(self, symbols: set[str] | None = None) -> int | None:
        """Fresh count of working orders, from any source. Waits for any command in progress,
        because two overlapping open-order requests to TWS would stall one of them."""
        async with self._lock:
            if not self.broker.connected:
                return None
            return await self.broker.open_orders(symbols or set(self.cfg.instruments))

    async def refresh_contracts(self) -> None:
        async with self._lock:
            if self.broker.connected:
                await self._refresh_contracts()

    async def _refresh_contracts(self) -> None:
        roll = self.cfg.safety.roll_days_before_expiry
        for sym, inst in self.cfg.enabled_instruments.items():
            new = await self.broker.front_month(inst, roll)
            old = self.contracts.get(sym)
            if old and not old.same_contract(new):
                if await self.broker.position(old):
                    # Never switch contracts under an open position: "sell" must keep closing it.
                    if sym not in self._roll_deferred:
                        self._roll_deferred.add(sym)
                        self.journal.log(
                            "contract_roll_deferred", symbol=sym, old=old.local_symbol, new=new.local_symbol
                        )
                        self.speaker.say(
                            f"{inst.label} roll to {new.local_symbol} waits until you're flat in {old.local_symbol}."
                        )
                    continue
                self._roll_deferred.discard(sym)
                self.journal.log("contract_roll", symbol=sym, old=old.local_symbol, new=new.local_symbol)
                self.speaker.say(f"Rolled {inst.label} to {new.local_symbol}.")
            self.contracts[sym] = new

    async def _warn_about_other_expiries(self) -> None:
        for c, q in await self.broker.positions(set(self.cfg.instruments)):
            front = self.contracts.get(c.symbol)
            if front is None:
                self.speaker.say(f"Heads up: you hold {describe_position(q)} {c.local_symbol}. Flatten closes it.")
            elif not front.same_contract(c):
                self.speaker.say(
                    f"Heads up: you hold {describe_position(q)} {c.local_symbol}. Buy and sell are blocked "
                    f"until it's closed. Say flatten."
                )

    # ---- entry points -----------------------------------------------------------------------

    async def handle_transcript(self, tr: Transcript, meta: Meta) -> None:
        meta.confidence = tr.confidence
        if tr.empty:
            await self.reject_input("silence", meta, "Didn't hear anything.")
        elif tr.has_unknown or tr.confidence < self.cfg.voice.min_confidence:
            reason = "unknown words" if tr.has_unknown else f"low confidence {tr.confidence:.2f}"
            await self.reject_input(reason, meta, "Didn't catch that.", text=tr.text)
        else:
            await self.handle_text(tr.text, meta)

    async def reject_input(
        self, reason: str, meta: Meta | None = None, said: str = "Didn't catch that.", text: str = ""
    ) -> None:
        """Anything unclear counts as 'not confirm': it also drops a pending order."""
        meta = meta or Meta(source="voice")
        async with self._lock:
            self.journal.log("heard", text=text, rejected=reason, **self._meta(meta))
            self._reject_reply(said)

    def _reject_reply(self, said: str) -> None:
        self._expire_pending()
        if self.pending:
            self.journal.log("cancelled", intent=self.pending.intent.describe(), by="unclear_input")
            self.pending = None
            self.speaker.say(f"{said} Order cancelled.", interrupt=True)
        else:
            self.speaker.say(f"{said} Nothing sent.", interrupt=True)

    async def handle_text(self, text: str, meta: Meta | None = None) -> None:
        meta = meta or Meta()
        async with self._lock:
            intent = self.parser.parse(text)
            self.journal.log("heard", text=text, intent=intent.describe() if intent else None, **self._meta(meta))
            if intent is None:
                self._reject_reply("Didn't catch that.")
                return
            try:
                await self._dispatch(intent, meta)
            except BrokerError as e:
                self.journal.log("error", error=str(e))
                self.speaker.say(f"Broker error. {e} {CHECK_PLATFORM}", interrupt=True)
            except Exception as e:  # never die mid-trade without saying so
                self.journal.log("error", error=repr(e))
                self.speaker.say(f"Something went wrong. Order state unknown. {CHECK_PLATFORM}", interrupt=True)

    # ---- dispatch -----------------------------------------------------------------------------

    async def _dispatch(self, intent: Intent, meta: Meta) -> None:
        expired = self._expire_pending()

        if intent.action is Action.CONFIRM:
            if self.pending is None:
                self.speaker.say("That order expired. Say it again." if expired else "Nothing to confirm.")
                return
            p, self.pending = self.pending, None
            self.journal.log("confirmed", intent=p.intent.describe())
            if p.intent.action is Action.FLATTEN:
                await self._flatten(p.intent.symbol, meta)
            else:
                await self._execute_trade(p.intent, p.current, meta)
            return

        if intent.action is Action.CANCEL:
            if self.pending:
                self.journal.log("cancelled", intent=self.pending.intent.describe(), by="user")
                self.pending = None
                self.speaker.say("Cancelled.")
            else:
                self.speaker.say("Nothing to cancel.")
            return

        # Any new command replaces an unconfirmed one.
        if self.pending:
            self.journal.log("cancelled", intent=self.pending.intent.describe(), by="new_command")
            self.pending = None

        if intent.action is Action.FLATTEN:
            if self.cfg.safety.confirm_flatten:
                self.pending = Pending(intent, 0, 0, self._mono())
                self._arm_expiry(self.pending)
                target = self.cfg.instruments[intent.symbol].label if intent.symbol else "everything"
                self.speaker.say(f"Flatten {target}. Say confirm.")
                self.journal.log("awaiting_confirm", intent=intent.describe())
                return
            await self._flatten(intent.symbol, meta)
            return

        await self._request_trade(intent, meta)

    def _arm_expiry(self, p: Pending) -> None:
        """Say "expired" when the confirm window runs out, instead of waiting for the next command."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        delay = self.cfg.safety.confirm_timeout_s + 0.05
        loop.call_later(delay, lambda: loop.create_task(self._expire_if_still(p)))

    async def _expire_if_still(self, p: Pending) -> None:
        async with self._lock:
            if self.pending is p:
                self.pending = None
                self.journal.log("cancelled", intent=p.intent.describe(), by="timeout")
                self.speaker.say("Order expired. Nothing sent.", interrupt=True)

    def _expire_pending(self) -> bool:
        p = self.pending
        if p and self._mono() - p.created > self.cfg.safety.confirm_timeout_s:
            self.journal.log("cancelled", intent=p.intent.describe(), by="timeout")
            self.pending = None
            return True
        return False

    # ---- buy / sell ---------------------------------------------------------------------------

    def _plan(self, intent: Intent, current: int) -> tuple[int, int]:
        qty = self.cfg.instruments[intent.symbol].quantity
        return qty, current + (qty if intent.action is Action.BUY else -qty)

    async def _precheck(self, intent: Intent) -> tuple[int, str | None]:
        """Current front-month position, or a reason this trade can't go ahead."""
        sym = intent.symbol
        if not self.broker.connected:
            return 0, "Not connected to the broker."
        front = self.contracts[sym]
        current = 0
        for c, q in await self.broker.positions({sym}):
            if c.same_contract(front):
                current += q
            else:
                # Limits and readbacks must see the whole position; mixed expiries make "sell" ambiguous.
                return 0, f"You hold {describe_position(q)} {c.local_symbol}, an older contract. Say flatten first."
        return current, None

    async def _block(self, intent: Intent, reason: str, **extra) -> None:
        self.journal.log("blocked", intent=intent.describe(), reason=reason, **extra)
        self.speaker.say(f"Blocked. {reason} Nothing sent.", interrupt=True)

    async def _request_trade(self, intent: Intent, meta: Meta) -> None:
        sym = intent.symbol
        inst = self.cfg.instruments[sym]
        current, problem = await self._precheck(intent)
        if problem:
            return await self._block(intent, problem)
        qty, resulting = self._plan(intent, current)
        decision = self.risk.check_order(sym, current, resulting)
        if not decision.ok:
            return await self._block(intent, decision.reason, position=current)

        if self.cfg.safety.require_confirmation:
            self.pending = Pending(intent, current, resulting, self._mono())
            self._arm_expiry(self.pending)
            verb = "Buy" if intent.action is Action.BUY else "Sell"
            self.journal.log(
                "awaiting_confirm", intent=intent.describe(), position=current, resulting=resulting, quantity=qty
            )
            self.speaker.say(
                f"{verb} {qty} {inst.label}. {describe_position(current).capitalize()} to "
                f"{describe_position(resulting)}. Say confirm.",
                interrupt=True,
            )
            return
        await self._execute_trade(intent, current, meta)

    async def _execute_trade(self, intent: Intent, expected_current: int, meta: Meta) -> None:
        sym = intent.symbol
        inst = self.cfg.instruments[sym]
        contract = self.contracts[sym]
        current, problem = await self._precheck(intent)
        if problem:
            return await self._block(intent, problem)
        if current != expected_current:
            return await self._block(
                intent, "Your position changed since the readback. Say it again.", was=expected_current, now=current
            )
        qty, resulting = self._plan(intent, current)
        decision = self.risk.check_order(sym, current, resulting)  # re-check: time and limits may have moved
        if not decision.ok:
            return await self._block(intent, decision.reason, position=current)

        action = intent.action.value
        result = await self._send(contract, action, qty, meta)
        expected = current + (result.filled if action == "BUY" else -result.filled)
        actual = await self._await_position(contract, expected, settle=not result.fully_filled)

        if result.fully_filled:
            past = "Bought" if action == "BUY" else "Sold"
            msg = (
                f"Filled. {past} {qty} {inst.label} at {_price(result.avg_price)}. You're {describe_position(actual)}."
            )
        elif result.status == "Unknown":
            msg = f"Order state unknown. {result.message} {CHECK_PLATFORM}"
        elif result.filled:
            msg = f"Partial fill, {result.filled} of {qty} at {_price(result.avg_price)}. {CHECK_PLATFORM}"
        else:
            if result.message and result.status in ("Inactive", "Cancelled", "ApiCancelled", "Rejected"):
                msg = f"{result.message} Nothing filled."
            else:
                msg = f"Order {result.status.lower()}. {result.message}".strip()
        if actual != expected:
            self.journal.log("position_mismatch", symbol=sym, expected=expected, broker=actual)
            msg += f" Warning: the broker shows you {describe_position(actual)}. {CHECK_PLATFORM}"
        self.speaker.say(msg, interrupt=True)

    # ---- flatten ------------------------------------------------------------------------------

    async def _flatten(self, symbol: str | None, meta: Meta) -> None:
        # Flatten-all covers every configured instrument, enabled or not.
        symbols = {symbol} if symbol else set(self.cfg.instruments)
        if not self.broker.connected:
            self.speaker.say("Not connected to the broker. Nothing sent.", interrupt=True)
            return
        decision = self.risk.check_flatten()
        if not decision.ok:
            self.journal.log("blocked", intent=f"FLATTEN {symbol or 'ALL'}", reason=decision.reason)
            self.speaker.say(f"Blocked. {decision.reason}", interrupt=True)
            return

        # Cancel working orders first, so a resting stop can't fire after we're flat. Only wait for
        # the ones Callout asked to cancel: orders it can't cancel won't go away, and every second
        # counts on the panic button.
        before = await self.broker.open_orders(symbols)
        cancelled = await self.broker.cancel_open_orders(symbols, self.cfg.safety.flatten_cancels_all_orders)
        still_working = await self._settle_open_orders(symbols, target=max(0, before - cancelled))
        self.journal.log("orders_cancelled", symbols=sorted(symbols), requested=cancelled, still_working=still_working)

        parts, problems = [], []
        for contract, qty in await self.broker.positions(symbols):
            action = "SELL" if qty > 0 else "BUY"
            result = await self._send(contract, action, abs(qty), meta)
            inst = self.cfg.instruments.get(contract.symbol)
            label = inst.label if inst else contract.symbol
            if result.fully_filled:
                past = "Sold" if action == "SELL" else "Bought"
                parts.append(f"{past} {abs(qty)} {label} at {_price(result.avg_price)}")
            else:
                problems.append(f"{contract.local_symbol}: {result.message or result.status.lower()}")

        left = await self._settle_positions(symbols)
        tail = ""
        if still_working:
            n = still_working
            tail = (
                f" Warning: {n} order{'s are' if n > 1 else ' is'} still working in TWS. "
                f"Cancel {'them' if n > 1 else 'it'} there."
            )
        self.journal.log("flatten_result", ok=not (problems or left), closed=parts, still_working=still_working)
        if problems or left:
            detail = "; ".join(problems) or ", ".join(f"{describe_position(q)} {c.local_symbol}" for c, q in left)
            self.journal.log("flatten_incomplete", problems=problems, remaining=[(c.local_symbol, q) for c, q in left])
            self.speaker.say(f"Flatten incomplete: {detail}. {CHECK_PLATFORM}{tail}", interrupt=True)
        elif parts:
            self.speaker.say("Flat. " + ". ".join(parts) + "." + tail, interrupt=True)
        else:
            extra = f" Cancelled {cancelled} working orders." if cancelled and not still_working else ""
            self.speaker.say(f"Already flat.{extra}{tail}", interrupt=True)

    # ---- helpers ------------------------------------------------------------------------------

    async def _send(self, contract: ContractRef, action: str, qty: int, meta: Meta) -> OrderResult:
        self.risk.record_order()
        t_sent = self._mono()
        self.journal.log("order_sent", contract=contract.local_symbol, action=action, quantity=qty, **self._meta(meta))
        try:
            result = await self.broker.market_order(contract, action, qty)
        except BrokerError as e:
            result = OrderResult("", action, qty, "Unknown", 0, None, str(e))
        t_done = self._mono()
        latency = {"send_to_done_ms": round((t_done - t_sent) * 1000, 1)}
        if meta.t_release is not None:
            latency["release_to_done_ms"] = round((t_done - meta.t_release) * 1000, 1)
        self.journal.log(
            "order_result",
            contract=contract.local_symbol,
            order_id=result.order_id,
            action=action,
            quantity=qty,
            status=result.status,
            filled=result.filled,
            avg_price=result.avg_price,
            message=result.message,
            **latency,
        )
        return result

    async def _await_position(
        self, contract: ContractRef, expected: int, timeout: float = 1.5, settle: bool = False
    ) -> int:
        """Ask the broker what the position really is after an order.

        After a fill, wait up to `timeout` for the broker to report it. After an
        order that didn't (fully) fill, always wait a short while anyway: a late
        fill is exactly what this is here to catch.
        """
        deadline = time.monotonic() + timeout
        if settle:
            await asyncio.sleep(0.5)
        try:
            pos = await self.broker.position(contract)
            while pos != expected and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                pos = await self.broker.position(contract)
        except BrokerError:
            return expected  # can't verify (e.g. disconnected); the order status message covers it
        return pos

    async def _settle_positions(self, symbols: set[str], timeout: float = 1.5) -> list[tuple[ContractRef, int]]:
        deadline = time.monotonic() + timeout
        held = await self.broker.positions(symbols)
        while held and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            held = await self.broker.positions(symbols)
        return held

    async def _settle_open_orders(self, symbols: set[str], target: int = 0, timeout: float = 3.0) -> int:
        """Wait (up to timeout) for working orders to drop to target. Returns how many are left."""
        deadline = time.monotonic() + timeout
        n = await self.broker.open_orders(symbols)
        while n > target and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            n = await self.broker.open_orders(symbols)
        return n

    def _meta(self, meta: Meta) -> dict:
        out: dict[str, Any] = {"source": meta.source}
        if meta.confidence is not None:
            out["confidence"] = round(meta.confidence, 3)
        if meta.t_release is not None and meta.t_heard is not None:
            out["stt_ms"] = round((meta.t_heard - meta.t_release) * 1000, 1)
        out.update(meta.extra)
        return out
