"""Command phrases: strict matching, instruments, and decoy words."""

import pytest

from callout.voice.intents import Action, Intent, IntentParser, normalize
from helpers import default_config as cfg


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
