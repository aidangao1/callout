"""Quarterly expiries, front-month choice and roll, position wording."""

from datetime import date

from callout.trading.contracts import (
    choose_front_month,
    describe_position,
    local_symbol,
    quarterly_expiries,
    third_friday,
)


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
