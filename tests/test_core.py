from datetime import date, datetime

import pytest

from callout.config import ConfigError, load_config
from callout.contracts import choose_front_month, describe_position, local_symbol, quarterly_expiries, third_friday
from callout.intents import Action, Intent, IntentParser, normalize
from callout.risk import ET, RiskManager, cme_equity_index_open


def cfg(tmp_path=None, **safety):
    c = load_config(None)
    for k, v in safety.items():
        setattr(c.safety, k, v)
    return c


# ---- intents ----------------------------------------------------------------------------------


def test_normalize():
    assert normalize("  Buy E.S. ") == "buy e s"
    assert normalize("SELL ES!") == "sell es"


def test_parser_strict_matching():
    p = IntentParser(cfg())
    assert p.parse("buy e s") == Intent(Action.BUY, "ES")
    assert p.parse("Sell ES") == Intent(Action.SELL, "ES")
    assert p.parse("buy e mini") == Intent(Action.BUY, "ES")
    assert p.parse("flatten") == Intent(Action.FLATTEN, None)
    assert p.parse("flatten es") == Intent(Action.FLATTEN, "ES")
    assert p.parse("confirm") == Intent(Action.CONFIRM)
    assert p.parse("cancel") == Intent(Action.CANCEL)
    for bad in ("buy", "es", "buy es now", "please buy es", "buy micro es", "sell nq", ""):
        assert p.parse(bad) is None, bad


def test_disabled_instrument_not_in_grammar():
    p = IntentParser(cfg())
    assert not any("micro" in g for g in p.grammar)


def test_enabling_micro():
    c = cfg()
    c.instruments["MES"].enabled = True
    p = IntentParser(c)
    assert p.parse("buy micro e s") == Intent(Action.BUY, "MES")
    assert p.parse("buy e s") == Intent(Action.BUY, "ES")


def test_ambiguous_phrases_rejected():
    c = cfg()
    c.instruments["MES"].enabled = True
    c.instruments["MES"].spoken = ["es"]
    with pytest.raises(ValueError):
        IntentParser(c)


# ---- config -----------------------------------------------------------------------------------


def test_template_config_loads():
    c = load_config("config.example.toml")
    assert c.broker.port == 7497 and c.broker.trading_mode == "paper"
    assert list(c.enabled_instruments) == ["ES"]


def test_paper_mode_on_live_port_is_rejected(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[broker]\nport = 7496\ntrading_mode = "paper"\n')
    with pytest.raises(ConfigError):
        load_config(f)


def test_unknown_keys_rejected(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[safety]\nmax_postion = 3\n")
    with pytest.raises(ConfigError):
        load_config(f)


# ---- contracts --------------------------------------------------------------------------------


def test_third_friday():
    assert third_friday(2026, 12) == date(2026, 12, 18)
    assert third_friday(2027, 3) == date(2027, 3, 19)


def test_front_month_and_roll():
    exps = [(d, d) for d in quarterly_expiries(date(2026, 11, 6), 3)]
    assert choose_front_month(exps, date(2026, 11, 6), 8)[0] == date(2026, 12, 18)
    assert choose_front_month(exps, date(2026, 12, 9), 8)[0] == date(2026, 12, 18)
    assert choose_front_month(exps, date(2026, 12, 10), 8)[0] == date(2027, 3, 19)  # rolled
    assert local_symbol("ES", date(2026, 12, 18)) == "ESZ6"


def test_describe_position():
    assert describe_position(0) == "flat"
    assert describe_position(2) == "long 2"
    assert describe_position(-1) == "short 1"


# ---- risk -------------------------------------------------------------------------------------


def et(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ET)


@pytest.mark.parametrize(
    "when,expected",
    [
        (et(2026, 11, 6, 19, 18), False),  # Friday evening: closed for the weekend
        (et(2026, 11, 7, 12), False),  # Saturday
        (et(2026, 11, 8, 17, 59), False),  # Sunday before open
        (et(2026, 11, 8, 18, 0), True),  # Sunday open
        (et(2026, 11, 9, 10), True),  # Monday morning
        (et(2026, 11, 9, 17, 30), False),  # daily halt
        (et(2026, 11, 9, 18, 1), True),  # after halt
        (et(2026, 11, 13, 16, 59), True),  # Friday before close
        (et(2026, 11, 13, 17, 0), False),  # Friday close
    ],
)
def test_market_hours(when, expected):
    assert cme_equity_index_open(when) is expected


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def open_risk(**safety):
    clock = Clock()
    r = RiskManager(cfg(**safety), monotonic=clock, now=lambda: et(2026, 11, 9, 10))
    return r, clock


def test_max_position():
    r, _ = open_risk(max_position=2)
    assert r.check_order("ES", 1, 2).ok
    assert not r.check_order("ES", 2, 3).ok
    assert not r.check_order("ES", -2, -3).ok
    assert r.check_order("ES", 3, 2).ok  # reducing is always allowed


def test_cooldown_and_rate_limit():
    r, clock = open_risk(min_seconds_between_orders=1.0, max_orders_per_minute=3)
    r.record_order()
    assert not r.check_order("ES", 0, 1).ok  # too fast
    clock.t += 1.1
    assert r.check_order("ES", 0, 1).ok
    r.record_order(); clock.t += 1.1
    r.record_order(); clock.t += 1.1
    assert "Rate limit" in r.check_order("ES", 0, 1).reason
    clock.t += 61
    assert r.check_order("ES", 0, 1).ok


def test_market_closed_blocks_orders_and_flatten():
    r = RiskManager(cfg(), now=lambda: et(2026, 11, 7, 12))
    assert not r.check_order("ES", 0, 1).ok
    assert not r.check_flatten().ok
    r.ignore_market_hours = True
    assert r.check_order("ES", 0, 1).ok


def test_decoys_are_heard_but_rejected():
    c = cfg()
    p = IntentParser(c)
    for word in ("flat", "close", "flatter"):
        assert word in p.grammar
        assert p.parse(word) is None
    assert p.parse("flatten") == Intent(Action.FLATTEN, None)
    assert p.parse("close all") == Intent(Action.FLATTEN, None)
    assert not set(p.decoys) & set(p.phrases)  # a decoy can never shadow a real command


def test_no_decoys_that_sound_like_e_s():
    """Decoys like "e", "s", "yes" or "by" ate the words of real commands in the paper test."""
    p = IntentParser(cfg())
    trade_words = {w for phrase in p.phrases if phrase.split()[0] in ("buy", "sell") for w in phrase.split()}
    for d in p.decoys:
        assert d not in trade_words, d
    for bad in ("e", "s", "es", "yes", "by", "bye", "cell", "buy", "sell"):
        assert bad not in p.decoys, bad


def test_extra_decoys_from_config():
    c = cfg()
    c.voice.decoys = ["Flatline", "flatten"]  # "flatten" is a real command, so it's ignored as a decoy
    p = IntentParser(c)
    assert "flatline" in p.decoys and "flatten" not in p.decoys
    assert p.parse("flatten") == Intent(Action.FLATTEN, None)


def test_settings_file_round_trip(tmp_path):
    from callout.settings_io import save_config

    c = load_config("config.example.toml")
    c.safety.max_position = 3
    c.voice.decoys = ["flatline"]
    c.instruments["MES"].enabled = True
    save_config(c, tmp_path / "config.toml")
    back = load_config(tmp_path / "config.toml")
    assert back.safety.max_position == 3 and back.voice.decoys == ["flatline"]
    assert back.instruments["MES"].enabled and back.instruments["ES"].spoken == c.instruments["ES"].spoken


def test_market_clock_text():
    from callout.risk import market_status_text

    assert market_status_text(et(2026, 11, 6, 21, 18)) == (False, "Market closed · opens Sun 6:00 PM ET")
    assert market_status_text(et(2026, 11, 9, 10)) == (True, "Market open · closes 5:00 PM ET")
    assert market_status_text(et(2026, 11, 12, 20)) == (True, "Market open · closes Fri 5:00 PM ET")
    assert market_status_text(et(2026, 11, 9, 17, 30)) == (False, "Market closed · opens 6:00 PM ET")
