import asyncio
from datetime import date, datetime

import pytest

from callout.brokers.sim import SimBroker
from callout.config import load_config
from callout.engine import Engine, Meta
from callout.journal import NullJournal
from callout.risk import ET, RiskManager
from callout.stt import Transcript
from callout.tts import SilentSpeaker


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(confirm=True, **safety):
    cfg = load_config(None)
    cfg.safety.require_confirmation = confirm
    cfg.safety.min_seconds_between_orders = 0
    for k, v in safety.items():
        setattr(cfg.safety, k, v)
    clock = Clock()
    risk = RiskManager(cfg, monotonic=clock, now=lambda: datetime(2026, 11, 9, 10, tzinfo=ET))
    broker = SimBroker(fill_delay_s=0, today=date(2026, 11, 9), seed=1)
    speaker, journal = SilentSpeaker(), NullJournal()
    engine = Engine(cfg, broker, speaker, journal, risk, monotonic=clock)
    asyncio.run(engine.start())
    return engine, broker, speaker, journal, clock


def say(engine, *lines):
    async def go():
        for line in lines:
            await engine.handle_text(line, Meta())

    asyncio.run(go())


def pos(engine, broker, sym="ES"):
    return asyncio.run(broker.position(engine.contracts[sym]))


def events(journal, name):
    return [r for r in journal.records if r["event"] == name]


def test_front_month_selected():
    engine, *_ = make()
    assert engine.contracts["ES"].local_symbol == "ESZ6"


def test_buy_requires_confirm_then_fills():
    engine, broker, speaker, journal, _ = make()
    say(engine, "buy es")
    assert pos(engine, broker) == 0
    assert speaker.said[-1] == "Buy 1 E S. Flat to long 1. Say confirm."
    say(engine, "confirm")
    assert pos(engine, broker) == 1
    assert speaker.said[-1].startswith("Filled. Bought 1 E S at ")
    assert speaker.said[-1].endswith("You're long 1.")
    assert len(events(journal, "order_result")) == 1


def test_sell_when_long_goes_flat_and_readback_says_so():
    engine, broker, speaker, *_ = make()
    say(engine, "buy es", "confirm", "sell es")
    assert "Long 1 to flat" in speaker.said[-1]
    say(engine, "confirm")
    assert pos(engine, broker) == 0
    assert speaker.said[-1].endswith("You're flat.")


def test_sell_when_flat_goes_short():
    engine, broker, speaker, *_ = make(confirm=False)
    say(engine, "sell e s")
    assert pos(engine, broker) == -1
    assert "Sold 1 E S" in speaker.said[-1] and "short 1" in speaker.said[-1]


def test_cancel_and_nothing_to_confirm():
    engine, broker, speaker, journal, _ = make()
    say(engine, "buy es", "cancel")
    assert speaker.said[-1] == "Cancelled."
    say(engine, "confirm")
    assert speaker.said[-1] == "Nothing to confirm."
    assert pos(engine, broker) == 0
    assert not events(journal, "order_sent")


def test_confirm_expires():
    engine, broker, speaker, _, clock = make(confirm_timeout_s=10)
    say(engine, "buy es")
    clock.t += 11
    say(engine, "confirm")
    assert speaker.said[-1] == "That order expired. Say it again."
    assert pos(engine, broker) == 0


def test_new_command_replaces_pending():
    engine, broker, speaker, *_ = make()
    say(engine, "buy es", "sell es", "confirm")
    assert pos(engine, broker) == -1


def test_position_changed_between_readback_and_confirm():
    engine, broker, speaker, *_ = make()
    say(engine, "buy es")
    broker.set_position(engine.contracts["ES"], 1)  # e.g. a manual fill in TWS meanwhile
    say(engine, "confirm")
    assert "position changed" in speaker.said[-1] and "Nothing sent" in speaker.said[-1]
    assert pos(engine, broker) == 1


def test_max_position_blocks():
    engine, broker, speaker, *_ = make(confirm=False, max_position=2)
    say(engine, "buy es", "buy es", "buy es")
    assert pos(engine, broker) == 2
    assert speaker.said[-1].startswith("Blocked.")


def test_flatten_closes_all_expiries_without_confirm():
    engine, broker, speaker, journal, _ = make()
    from callout.brokers.base import ContractRef

    old = ContractRef("ES", "ESU6", date(2026, 9, 18))
    broker.set_position(old, -1)
    broker.set_position(engine.contracts["ES"], 2)
    say(engine, "flatten")
    assert asyncio.run(broker.positions({"ES"})) == []
    assert speaker.said[-1].startswith("Flat.")
    assert len(events(journal, "order_result")) == 2


def test_flatten_when_already_flat():
    engine, broker, speaker, *_ = make()
    say(engine, "flatten")
    assert speaker.said[-1] == "Already flat."


def test_rejected_order_is_reported():
    engine, broker, speaker, *_ = make(confirm=False)
    broker.reject_next = "No trading permissions for futures."
    say(engine, "buy es")
    assert pos(engine, broker) == 0
    assert speaker.said[-1] == "Order rejected. No trading permissions for futures."


def test_unknown_text_does_nothing():
    engine, broker, speaker, journal, _ = make(confirm=False)
    say(engine, "buy es now please")
    assert speaker.said[-1] == "Didn't catch that. Nothing sent."
    assert not events(journal, "order_sent")


def test_low_confidence_voice_rejected():
    engine, broker, speaker, journal, _ = make(confirm=False)

    async def go():
        await engine.handle_transcript(Transcript("buy e s", 0.4, False), Meta(source="voice"))
        await engine.handle_transcript(Transcript("buy e s [unk]", 0.9, True), Meta(source="voice"))
        await engine.handle_transcript(Transcript("", 0.0, False), Meta(source="voice"))

    asyncio.run(go())
    assert pos(engine, broker) == 0
    assert [r.get("rejected") for r in events(journal, "heard")] == ["low confidence 0.40", "unknown words", "silence"]


def test_confident_voice_trades_and_logs_latency():
    engine, broker, speaker, journal, _ = make(confirm=False)
    import time

    t = time.monotonic()

    async def go():
        await engine.handle_transcript(
            Transcript("buy e s", 0.95, False), Meta(source="voice", t_release=t, t_heard=t + 0.2)
        )

    asyncio.run(go())
    assert pos(engine, broker) == 1
    result = events(journal, "order_result")[0]
    assert "release_to_done_ms" in result and "send_to_done_ms" in result
    assert events(journal, "heard")[0]["stt_ms"] == pytest.approx(200, abs=1)


def test_market_closed_blocks_everything():
    cfg = load_config(None)
    risk = RiskManager(cfg, now=lambda: datetime(2026, 11, 7, 12, tzinfo=ET))  # Saturday
    broker = SimBroker(fill_delay_s=0, today=date(2026, 11, 7))
    speaker, journal = SilentSpeaker(), NullJournal()
    engine = Engine(cfg, broker, speaker, journal, risk)
    asyncio.run(engine.start())
    say(engine, "buy es")
    assert speaker.said[-1] == "Blocked. Market is closed. Nothing sent."
    say(engine, "flatten")
    assert speaker.said[-1].startswith("Blocked.")


def test_heads_up_for_old_contract_at_startup():
    cfg = load_config(None)
    broker = SimBroker(fill_delay_s=0, today=date(2026, 11, 9))
    from callout.brokers.base import ContractRef

    broker.set_position(ContractRef("ES", "ESU6", date(2026, 9, 18)), 1)
    speaker = SilentSpeaker()
    engine = Engine(cfg, broker, speaker, NullJournal())
    asyncio.run(engine.start())
    assert "ESU6" in speaker.said[0] and "flatten" in speaker.said[0]


# ---- regression tests for the independent review findings -------------------------------------

from callout.brokers.base import BrokerError, ContractRef  # noqa: E402


def test_flatten_warns_about_orders_it_cannot_cancel():
    engine, broker, speaker, *_ = make()
    broker.set_position(engine.contracts["ES"], 1)
    broker.working = {"A": ("ES", True), "B": ("ES", False)}  # B was entered by hand in TWS
    say(engine, "flatten")
    assert speaker.said[-1].startswith("Flat. Sold 1 E S")
    assert "1 working order I couldn't cancel" in speaker.said[-1]
    assert broker.working == {"B": ("ES", False)}


def test_flatten_global_cancel_option_clears_everything():
    engine, broker, speaker, *_ = make(flatten_cancels_all_orders=True)
    broker.working = {"A": ("ES", True), "B": ("ES", False)}
    say(engine, "flatten")
    assert broker.working == {}
    assert speaker.said[-1] == "Already flat. Cancelled 2 working orders."


def test_broker_exception_during_order_is_reported_not_raised():
    engine, broker, speaker, journal, _ = make(confirm=False)
    broker.raise_next = BrokerError("Order not sent: Not connected")
    say(engine, "buy es")
    assert speaker.said[-1].startswith("Order state unknown.")
    broker.raise_next = RuntimeError("library bug")
    say(engine, "sell es")
    assert "Something went wrong" in speaker.said[-1]
    say(engine, "flatten")  # app is still alive and flatten still works
    assert speaker.said[-1] == "Already flat."


def test_older_expiry_blocks_buy_sell_and_counts_toward_limits():
    engine, broker, speaker, journal, _ = make(confirm=False, max_position=2)
    broker.set_position(ContractRef("ES", "ESU6", date(2026, 9, 18)), 2)
    say(engine, "buy es")
    assert speaker.said[-1].startswith("Blocked. You hold long 2 ESU6")
    assert not events(journal, "order_sent")
    say(engine, "flatten", "buy es")
    assert pos(engine, broker) == 1


def test_roll_waits_while_holding_the_old_contract():
    engine, broker, speaker, journal, _ = make(confirm=False)
    say(engine, "buy es")
    broker._today = date(2026, 12, 11)  # inside the roll window
    asyncio.run(engine.refresh_contracts())
    assert engine.contracts["ES"].local_symbol == "ESZ6"
    assert "waits until you're flat" in speaker.said[-1]
    say(engine, "sell es")  # still closes the Dec contract
    assert pos(engine, broker) == 0
    asyncio.run(engine.refresh_contracts())
    assert engine.contracts["ES"].local_symbol == "ESH7"


def test_late_fill_after_timeout_is_caught():
    engine, broker, speaker, journal, _ = make(confirm=False)
    broker.silent_fill_next = True
    say(engine, "buy es")
    assert speaker.said[-1].startswith("Order timeout.")
    assert "broker shows you long 1" in speaker.said[-1]
    assert events(journal, "position_mismatch")


def test_flatten_all_includes_disabled_instruments():
    engine, broker, speaker, *_ = make()
    assert not engine.cfg.instruments["MES"].enabled
    broker.set_position(ContractRef("MES", "MESZ6", date(2026, 12, 18)), -3)
    say(engine, "flatten")
    assert asyncio.run(broker.positions({"MES"})) == []
    assert speaker.said[-1] == f"Flat. Bought 3 micro E S at {speaker.said[-1].split(' at ')[1]}"


def test_unclear_utterance_cancels_pending_order():
    engine, broker, speaker, journal, _ = make()
    say(engine, "buy es")

    async def mumble():
        await engine.handle_transcript(Transcript("cancel", 0.5, False), Meta(source="voice"))

    asyncio.run(mumble())
    assert speaker.said[-1] == "Didn't catch that. Order cancelled."
    say(engine, "confirm")
    assert speaker.said[-1] == "Nothing to confirm."
    assert pos(engine, broker) == 0

    say(engine, "buy es", "buy es please")  # unparsed text cancels too
    assert speaker.said[-1] == "Didn't catch that. Order cancelled."

    say(engine, "buy es")
    asyncio.run(engine.reject_input("too short", said="Too short."))
    assert speaker.said[-1] == "Too short. Order cancelled."
    assert pos(engine, broker) == 0


def test_disconnected_broker_blocks_trades():
    engine, broker, speaker, journal, _ = make(confirm=False)
    asyncio.run(broker.disconnect())
    say(engine, "buy es")
    assert speaker.said[-1] == "Blocked. Not connected to the broker. Nothing sent."
    asyncio.run(engine.start())  # reconnect path
    say(engine, "buy es")
    assert pos(engine, broker) == 1
