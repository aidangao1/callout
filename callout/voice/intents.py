"""Turns a transcript into a structured command.

Matching is deliberately strict: the whole utterance has to equal one of the
known phrases. Anything else is rejected rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from ..config import Config


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLATTEN = "FLATTEN"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"


@dataclass(frozen=True)
class Intent:
    action: Action
    symbol: str | None = None  # None for FLATTEN-all, CONFIRM, CANCEL

    def describe(self) -> str:
        return f"{self.action.value} {self.symbol}" if self.symbol else self.action.value


# Words that sound like commands but aren't. The recognizer can only output phrases it
# knows, so without these, "flat" gets rounded to "flatten". With them it hears the decoy,
# which the parser rejects.
#
# Only near-misses of FLATTEN are listed: it acts immediately, with no readback. Buy and
# sell are always read back first, so a near-miss there is harmless, while decoys that
# sound like "E S" ("e", "s", "yes", "by"...) split the recognizer's attention and made it
# reject clearly spoken commands (see the 2026-11-09 paper test log).
DECOYS = (
    "flat",
    "flats",
    "flattened",
    "flatter",
    "fat",
    "that",
    "close",
    "clothes",
    "all",
)

CONFIRM_WORDS = ("confirm", "yes confirm")
CANCEL_WORDS = ("cancel", "no")
FLATTEN_ALL = ("flatten", "flatten all", "close all")


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse spaces. 'Buy E.S.' -> 'buy e s'."""
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_phrase_map(cfg: Config) -> dict[str, Intent]:
    phrases: dict[str, Intent] = {}

    def add(phrase: str, intent: Intent) -> None:
        phrase = normalize(phrase)
        if phrase in phrases and phrases[phrase] != intent:
            raise ValueError(f"Spoken phrase '{phrase}' is ambiguous ({phrases[phrase]} vs {intent})")
        phrases[phrase] = intent

    for symbol, inst in cfg.enabled_instruments.items():
        for alias in inst.spoken:
            add(f"buy {alias}", Intent(Action.BUY, symbol))
            add(f"sell {alias}", Intent(Action.SELL, symbol))
            add(f"flatten {alias}", Intent(Action.FLATTEN, symbol))
    for p in FLATTEN_ALL:
        add(p, Intent(Action.FLATTEN, None))
    for p in CONFIRM_WORDS:
        add(p, Intent(Action.CONFIRM))
    for p in CANCEL_WORDS:
        add(p, Intent(Action.CANCEL))
    return phrases


class IntentParser:
    def __init__(self, cfg: Config):
        self.phrases = build_phrase_map(cfg)
        extra = tuple(getattr(cfg.voice, "decoys", ()) or ())
        self.decoys = sorted({normalize(d) for d in DECOYS + extra} - set(self.phrases) - {""})

    def parse(self, text: str) -> Intent | None:
        return self.phrases.get(normalize(text))

    @property
    def grammar(self) -> list[str]:
        """Every phrase the recognizer is allowed to output: commands plus decoys."""
        return sorted(self.phrases) + self.decoys
