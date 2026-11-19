"""Hands-free listening from the phone: what Callout acts on and what it ignores.

The phone's mic is always on, so it hears the game, other players, everything. Callout
only acts on speech that starts with the wake word ("call out ..."). The one exception:
while an order is waiting for confirm, a bare "confirm" or "cancel" counts, because
that's what the readback asks for.
"""

from __future__ import annotations

from ..voice.intents import CANCEL_WORDS, CONFIRM_WORDS, IntentParser

WAKE = "call out"  # two words: the speech model's vocabulary has them; "callout" may not be


def phone_grammar(parser: IntentParser) -> list[str]:
    """The phrases the recognizer may hear from the phone."""
    woken = [f"{WAKE} {p}" for p in parser.phrases]
    return sorted(set(woken) | set(CONFIRM_WORDS) | set(CANCEL_WORDS)) + parser.decoys


def route(text: str, has_unknown: bool, pending: bool) -> tuple[str, str]:
    """Decide what to do with something heard on the phone.

    Returns ("command", what to hand the engine), or ("ignore", why).
    """
    words = text.split()
    if not words:
        return "ignore", "silence"
    if " ".join(words[:2]) == WAKE or words[0] == "callout":
        rest = " ".join(words[1:] if words[0] == "callout" else words[2:])
        if not rest:
            return "ignore", "wake word only"
        return "command", rest  # unclear words after the wake word get "Didn't catch that"
    if pending and not has_unknown and text in CONFIRM_WORDS + CANCEL_WORDS:
        return "command", text
    return "ignore", "no wake word"
