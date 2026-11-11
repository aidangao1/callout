"""The Settings screen's logic on its own: applying a change, rolling back a bad one, live mode."""

import pytest

from callout.app.settings import apply_patch, settings_view
from callout.config import ConfigError
from helpers import default_config


def test_view_reflects_config():
    cfg = default_config()
    view = settings_view(cfg, use_sim=True)
    assert view["es_enabled"] and not view["mes_enabled"]
    assert view["app"] == "tws" and view["mode"] == "paper" and view["port"] == 7497
    assert view["sim"] is True


def test_simple_change_and_what_it_needs():
    cfg = default_config()
    applied = apply_patch(cfg, {"max_position": 3, "tts": False}, live_unlocked=True)
    assert cfg.safety.max_position == 3 and cfg.voice.tts is False
    assert applied.needs == set()
    assert apply_patch(cfg, {"push_to_talk": " F8 "}, True).needs == {"talker"}
    assert cfg.voice.push_to_talk == "f8"
    assert apply_patch(cfg, {"mes_enabled": True}, True).needs == {"grammar"}


def test_bad_change_rolls_everything_back():
    cfg = default_config()
    with pytest.raises(ConfigError, match="max_position"):
        apply_patch(cfg, {"quantity": 1, "max_position": 0}, True)
    assert cfg.safety.max_position == 2
    with pytest.raises(ConfigError, match="Unknown setting"):
        apply_patch(cfg, {"tts": False, "nonsense": 1}, True)
    assert cfg.voice.tts is True  # the valid part of a rejected change is undone too


def test_live_needs_typed_confirmation_and_ports_follow_the_choice():
    cfg = default_config()
    with pytest.raises(ConfigError, match="LIVE"):
        apply_patch(cfg, {"mode": "live", "app": "tws"}, live_unlocked=True)
    assert cfg.broker.trading_mode == "paper"
    applied = apply_patch(cfg, {"mode": "live", "app": "tws", "live_confirm": "LIVE"}, live_unlocked=True)
    assert (cfg.broker.trading_mode, cfg.broker.port) == ("live", 7496)
    assert "connection" in applied.needs and applied.live_unlocked
    apply_patch(cfg, {"mode": "paper", "app": "gateway"}, live_unlocked=True)
    assert cfg.broker.port == 4002
