"""The Settings screen: what it shows, and applying its changes to the config.

apply_patch() only changes the config (and undoes everything if the change is
invalid). The session then does the side effects: saving, restarting the mic,
reconnecting.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields

from ..config import (
    DEFAULT_INSTRUMENTS,
    BrokerConfig,
    Config,
    ConfigError,
    Instrument,
    SafetyConfig,
    VoiceConfig,
    app_for_port,
    default_port,
    validate,
)
from ..voice.intents import IntentParser, normalize

_LIGHT_SAFETY = {
    "require_confirmation": bool,
    "confirm_flatten": bool,
    "flatten_cancels_all_orders": bool,
    "max_position": int,
    "min_seconds_between_orders": float,
    "max_orders_per_minute": int,
    "check_market_hours": bool,
    "confirm_timeout_s": float,
}
_CONNECTION_KEYS = {"app", "mode", "port", "host", "live_confirm"}


def _restore(cfg: Config, before: Config) -> None:
    """Put cfg back exactly as it was, in place (the engine holds this same object)."""
    for name, cls in (("broker", BrokerConfig), ("voice", VoiceConfig), ("safety", SafetyConfig)):
        for f in fields(cls):
            setattr(getattr(cfg, name), f.name, copy.deepcopy(getattr(getattr(before, name), f.name)))
    cfg.instruments.clear()
    cfg.instruments.update(copy.deepcopy(before.instruments))


@dataclass
class Applied:
    needs: set[str] = field(default_factory=set)  # "grammar", "talker" and/or "connection"
    live_unlocked: bool = False


def settings_view(cfg: Config, use_sim: bool) -> dict:
    """Everything the Settings screen shows, as plain values."""
    c = cfg
    return {
        "es_enabled": c.instruments.get("ES", Instrument("ES", enabled=False)).enabled,
        "mes_enabled": c.instruments.get("MES", Instrument("MES", enabled=False)).enabled,
        "quantity": next((i.quantity for i in c.enabled_instruments.values()), 1),
        "max_position": c.safety.max_position,
        "check_market_hours": c.safety.check_market_hours,
        "min_seconds_between_orders": c.safety.min_seconds_between_orders,
        "max_orders_per_minute": c.safety.max_orders_per_minute,
        "require_confirmation": c.safety.require_confirmation,
        "confirm_flatten": c.safety.confirm_flatten,
        "flatten_cancels_all_orders": c.safety.flatten_cancels_all_orders,
        "app": app_for_port(c.broker.port),
        "mode": c.broker.trading_mode,
        "port": c.broker.port,
        "host": c.broker.host,
        "input_device": c.voice.input_device,
        "push_to_talk": c.voice.push_to_talk,
        "tts": c.voice.tts,
        "voice_rate": c.voice.voice_rate,
        "voice_volume": c.voice.voice_volume,
        "decoys": list(c.voice.decoys),
        "sim": use_sim,
    }


def apply_patch(cfg: Config, patch: dict, live_unlocked: bool) -> Applied:
    """Apply a Settings change to cfg, in place. On any problem, cfg is restored and ConfigError raised."""
    before = copy.deepcopy(cfg)
    needs: set[str] = set()
    try:
        for k, v in patch.items():
            if k in _CONNECTION_KEYS:
                continue
            if k in _LIGHT_SAFETY:
                setattr(cfg.safety, k, _LIGHT_SAFETY[k](v))
            elif k == "quantity":
                for inst in cfg.instruments.values():
                    inst.quantity = int(v)
            elif k == "tts":
                cfg.voice.tts = bool(v)
            elif k == "voice_rate":
                cfg.voice.voice_rate = max(-10, min(10, int(v)))
            elif k == "voice_volume":
                cfg.voice.voice_volume = max(0, min(100, int(v)))
            elif k == "min_confidence":
                cfg.voice.min_confidence = float(v)
            elif k == "input_device":
                cfg.voice.input_device = str(v)
                needs.add("talker")
            elif k == "push_to_talk":
                cfg.voice.push_to_talk = str(v).strip().lower()
                needs.add("talker")
            elif k == "decoys":
                cfg.voice.decoys = sorted({normalize(d) for d in v if normalize(d)})
                needs.add("grammar")
            elif k in ("es_enabled", "mes_enabled"):
                sym = "ES" if k == "es_enabled" else "MES"
                if sym not in cfg.instruments:
                    cfg.instruments[sym] = copy.deepcopy(DEFAULT_INSTRUMENTS[sym])
                cfg.instruments[sym].enabled = bool(v)
                needs.add("grammar")
            else:
                raise ConfigError(f"Unknown setting: {k}")

        if _CONNECTION_KEYS & set(patch):
            live_unlocked = _apply_connection(cfg, patch, live_unlocked, needs)
        validate(cfg)
        if "grammar" in needs:
            IntentParser(cfg)  # raises if two phrases collide; checked before anything changes
    except (ConfigError, ValueError, TypeError) as e:
        _restore(cfg, before)
        raise ConfigError(str(e)) from e
    return Applied(needs, live_unlocked)


def _apply_connection(cfg: Config, patch: dict, live_unlocked: bool, needs: set[str]) -> bool:
    app = patch.get("app") or app_for_port(cfg.broker.port)
    mode = patch.get("mode") or cfg.broker.trading_mode
    if mode not in ("paper", "live") or app not in ("tws", "gateway"):
        raise ConfigError("Unknown connection type.")
    already_live = cfg.broker.trading_mode == "live" and live_unlocked
    if mode == "live" and not already_live and (patch.get("live_confirm") or "").strip() != "LIVE":
        raise ConfigError("Type LIVE to switch to real-money trading.")
    changed_type = mode != cfg.broker.trading_mode or app != app_for_port(cfg.broker.port)
    custom_port = patch.get("port") not in (None, "") and not changed_type
    port = int(patch["port"]) if custom_port else default_port(app, mode)
    host = patch.get("host") or cfg.broker.host
    if (cfg.broker.trading_mode, cfg.broker.port, cfg.broker.host) != (mode, port, host):
        needs.add("connection")
    cfg.broker.trading_mode, cfg.broker.port, cfg.broker.host = mode, port, host
    return True  # live was just confirmed, or it's paper (which never needs unlocking)
