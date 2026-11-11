"""Small helpers shared by the tests."""

from datetime import datetime

from callout.config import load_config
from callout.trading.market_hours import ET


class Clock:
    """A fake monotonic clock: tests move time forward with clock.t += seconds."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in US Eastern time."""
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def default_config(**safety):
    """The default config, with any [safety] values overridden."""
    c = load_config(None)
    for k, v in safety.items():
        setattr(c.safety, k, v)
    return c
