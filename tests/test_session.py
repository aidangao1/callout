"""The window's backend, driven against the simulator with no mic or speakers."""

import time

import pytest

from callout.config import load_config
from callout.session import Session, feed_row


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def session(tmp_path):
    cfg = load_config(None)
    cfg.log_dir = str(tmp_path / "logs")
    cfg.safety.check_market_hours = False
    cfg.safety.min_seconds_between_orders = 0
    s = Session(cfg, tmp_path / "config.toml", use_sim=True, audio=False, tts=False)
    s.start()
    assert wait_for(lambda: s.snapshot().get("connected"))
    yield s
    s.stop()


def test_snapshot_shows_connection_and_sim_badge(session):
    snap = session.snapshot()
    assert snap["badge"] == "SIM" and snap["account"] == "SIM-PAPER"
    assert snap["instruments"][0]["symbol"] == "ES" and snap["instruments"][0]["position"] == "flat"
    assert snap["instruments"][0]["contract"].startswith("ES")
    assert "Market" in snap["market_text"]


def test_buttons_go_through_the_same_confirm_path(session):
    session.command("buy es")
    assert wait_for(lambda: session.snapshot()["pending"] is not None)
    p = session.snapshot()["pending"]
    assert p["verb"] == "Buy" and p["from"] == "flat" and p["to"] == "long 1" and 0 < p["left"] <= 10
    session.command("confirm")
    assert wait_for(lambda: session.snapshot()["instruments"][0]["qty"] == 1)
    snap = session.snapshot()
    assert snap["pending"] is None
    assert snap["last"]["kind"] == "filled" and snap["last"]["text"].startswith("Filled.")
    assert snap["instruments"][0]["avg"] is not None
    kinds = [r["kind"] for r in session.snapshot()["feed"]]
    assert kinds[:3] == ["Filled", "Confirmed", "Button"]


def test_flatten_button(session):
    session.command("buy es")
    session.command("confirm")
    assert wait_for(lambda: session.snapshot()["instruments"][0]["qty"] == 1)
    session.command("flatten")
    assert wait_for(lambda: session.snapshot()["instruments"][0]["qty"] == 0)
    assert session.snapshot()["last"]["text"].startswith("Flat.")


def test_feed_only_resent_when_it_changes(session):
    v = session.snapshot()["feed_version"]
    assert "feed" not in session.snapshot(v)
    assert "feed" in session.snapshot(-1)


def test_light_settings_apply_and_save(session):
    r = session.apply({"require_confirmation": False, "quantity": 2, "max_position": 4})
    assert r["ok"], r
    assert session.cfg.safety.require_confirmation is False
    assert session.cfg.instruments["ES"].quantity == 2
    text = session.config_path.read_text()
    assert "require_confirmation = false" in text and "max_position = 4" in text
    session.command("buy es")
    assert wait_for(lambda: session.snapshot()["instruments"][0]["qty"] == 2)


def test_bad_settings_are_rolled_back(session):
    r = session.apply({"max_position": 0, "quantity": 1})
    assert not r["ok"] and "max_position" in r["error"]
    assert session.cfg.safety.max_position == 2


def test_enabling_mes_adds_its_contract_and_phrases(session):
    r = session.apply({"mes_enabled": True})
    assert r["ok"], r
    assert wait_for(lambda: len(session.snapshot()["instruments"]) == 2)
    assert session.engine.parser.parse("buy micro e s") is not None
    r = session.apply({"es_enabled": False, "mes_enabled": False})
    assert not r["ok"]  # at least one instrument must stay on
    assert session.cfg.instruments["MES"].enabled


def test_live_needs_typed_confirmation(session):
    r = session.apply({"mode": "live", "app": "tws"})
    assert not r["ok"] and "LIVE" in r["error"]
    assert session.cfg.broker.trading_mode == "paper" and session.cfg.broker.port == 7497
    r = session.apply({"mode": "live", "app": "tws", "live_confirm": "LIVE"})
    assert r["ok"], r
    assert session.cfg.broker.trading_mode == "live" and session.cfg.broker.port == 7496
    r = session.apply({"mode": "paper", "app": "gateway"})
    assert r["ok"] and session.cfg.broker.port == 4002


def test_live_config_starts_locked(tmp_path):
    cfg = load_config(None)
    cfg.log_dir = str(tmp_path / "logs")
    cfg.broker.trading_mode, cfg.broker.port = "live", 7496
    s = Session(cfg, tmp_path / "config.toml", use_sim=True, audio=False, tts=False)
    s.start()
    try:
        assert wait_for(lambda: s.snapshot().get("ready"))
        time.sleep(0.3)
        snap = s.snapshot()
        assert snap["live_locked"] and not snap["connected"]
        assert not s.unlock_live("live")["ok"]
        assert s.unlock_live("LIVE")["ok"]
        assert wait_for(lambda: s.snapshot().get("connected"))
    finally:
        s.stop()


def test_test_connection_with_simulator(session):
    r = session.test_connection("tws", "paper")
    assert r["ok"] and r["account"] == "SIM-PAPER"


def test_feed_row_wording():
    assert feed_row({"event": "heard", "ts": "2026-11-09T10:00:01.000-05:00", "text": "buy e s", "intent": "BUY ES",
                     "source": "voice", "stt_ms": 240.0})["text"] == '"buy e s" → Buy ES'
    r = feed_row({"event": "order_result", "ts": "2026-11-09T10:00:02.500-05:00", "status": "Filled", "action": "SELL",
                  "filled": 1, "contract": "ESZ6", "avg_price": 6003.5, "release_to_done_ms": 1400.0})
    assert r["kind"] == "Filled" and r["text"] == "Sold 1 ESZ6 at 6003.50" and r["meta"] == "1.4 s" and r["time"] == "10:00:02"
    assert feed_row({"event": "shutdown"}) is None


def test_flatten_with_manual_order_shows_warning_until_cancelled(session):
    front = session.engine.contracts["ES"]
    session.broker.set_position(front, 1)
    session.broker.working = {"MANUAL-STOP": ("ES", False)}  # placed by hand in TWS
    session.command("flatten")
    assert wait_for(lambda: session.snapshot()["leftover"] == 1)
    snap = session.snapshot()
    assert snap["instruments"][0]["qty"] == 0
    assert snap["last"]["kind"] == "flat_warn" and snap["last"]["working"] == 1
    assert snap["working"] == 1
    assert session.snapshot(-1)["feed"][0]["kind"] == "Warning"
    del session.broker.working["MANUAL-STOP"]  # cancelled in TWS
    assert wait_for(lambda: session.snapshot()["leftover"] == 0, timeout=4)
    assert session.snapshot()["working"] == 0


def test_no_warning_when_flatten_cancels_everything(session):
    session.broker.set_position(session.engine.contracts["ES"], -1)
    session.broker.working = {"OWN": ("ES", True)}
    session.command("flatten")
    assert wait_for(lambda: session.snapshot()["instruments"][0]["qty"] == 0)
    time.sleep(0.3)
    snap = session.snapshot()
    assert snap["leftover"] == 0 and snap["last"]["kind"] == "filled"
