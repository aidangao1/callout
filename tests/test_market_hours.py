"""When ES trades, and the status-bar wording."""

import pytest

from callout.trading.market_hours import cme_equity_index_open, market_status_text
from helpers import et


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


def test_market_clock_text():
    assert market_status_text(et(2026, 11, 6, 21, 18)) == (False, "Market closed · opens Sun 6:00 PM ET")
    assert market_status_text(et(2026, 11, 9, 10)) == (True, "Market open · closes 5:00 PM ET")
    assert market_status_text(et(2026, 11, 12, 20)) == (True, "Market open · closes Fri 5:00 PM ET")
    assert market_status_text(et(2026, 11, 9, 17, 30)) == (False, "Market closed · opens 6:00 PM ET")
