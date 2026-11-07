"""Turns a transcript into a structured command.

Matching is deliberately strict: the whole utterance has to equal one of the
known phrases. Anything else is rejected rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .config import Config


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

    def parse(self, text: str) -> Intent | None:
        return self.phrases.get(normalize(text))

    @property
    def grammar(self) -> list[str]:
        """Every phrase the recognizer is allowed to output."""
        return sorted(self.phrases)
