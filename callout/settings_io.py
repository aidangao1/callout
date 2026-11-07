"""Save a Config back to config.toml (the app's Settings screen writes through this)."""

from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path

import tomli_w

from .config import BrokerConfig, Config, SafetyConfig, VoiceConfig

HEADER = (
    "# Callout settings. The app's Settings screen writes this file;\n"
    "# you can also edit it by hand while Callout is closed.\n\n"
)

PORTS = {("tws", "paper"): 7497, ("tws", "live"): 7496, ("gateway", "paper"): 4002, ("gateway", "live"): 4001}


def default_port(app: str, mode: str) -> int:
    return PORTS[(app, mode)]


def app_for_port(port: int) -> str:
    return "gateway" if port in (4001, 4002) else "tws"


def config_to_dict(cfg: Config) -> dict:
    def section(obj, cls) -> dict:
        return {f.name: getattr(obj, f.name) for f in fields(cls)}

    instruments = {}
    for sym, inst in cfg.instruments.items():
        d = asdict(inst)
        d.pop("symbol", None)
        if d.get("max_position") is None:
            d.pop("max_position")
        instruments[sym] = d
    return {
        "log_dir": cfg.log_dir,
        "broker": section(cfg.broker, BrokerConfig),
        "voice": section(cfg.voice, VoiceConfig),
        "safety": section(cfg.safety, SafetyConfig),
        "instruments": instruments,
    }


def save_config(cfg: Config, path: str | Path) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(HEADER + tomli_w.dumps(config_to_dict(cfg)), encoding="utf-8")
    tmp.replace(path)  # atomic on the same drive: a crash never leaves half a file
