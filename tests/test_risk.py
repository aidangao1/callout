"""Position limit, order pace and the market-hours block."""

from callout.trading.risk import RiskManager
from helpers import Clock, et
from helpers import default_config as cfg


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
    r.record_order()
    clock.t += 1.1
    r.record_order()
    clock.t += 1.1
    assert "Rate limit" in r.check_order("ES", 0, 1).reason
    clock.t += 61
    assert r.check_order("ES", 0, 1).ok


def test_market_closed_blocks_orders_and_flatten():
    r = RiskManager(cfg(), now=lambda: et(2026, 11, 7, 12))
    assert not r.check_order("ES", 0, 1).ok
    assert not r.check_flatten().ok
    r.ignore_market_hours = True
    assert r.check_order("ES", 0, 1).ok
