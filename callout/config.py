"""Settings: the config.toml file, loaded into plain dataclasses, validated, and saved back."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w

TEMPLATE = Path(__file__).with_name("config_template.toml")

# Standard Interactive Brokers API ports, by (app, account type).
PORTS = {("tws", "paper"): 7497, ("tws", "live"): 7496, ("gateway", "paper"): 4002, ("gateway", "live"): 4001}
LIVE_PORTS = {7496, 4001}
PAPER_PORTS = {7497, 4002}


class ConfigError(ValueError):
    pass


@dataclass
class BrokerConfig:
    type: str = "ibkr"  # "ibkr" or "sim"
    host: str = "127.0.0.1"
    port: int = 7497  # TWS paper 7497 | TWS live 7496 | Gateway paper 4002 | Gateway live 4001
    client_id: int = 17
    account: str = ""  # blank = first account on the login
    trading_mode: str = "paper"  # "paper" or "live"
    order_timeout_s: float = 10.0


@dataclass
class VoiceConfig:
    model: str = "vosk-model-small-en-us-0.15"  # model name (auto-downloads) or a folder path
    push_to_talk: str = "f9"  # a key name like "f9", "ctrl_r", "scroll_lock", or "enter"
    min_confidence: float = 0.70
    sample_rate: int = 0  # 0 = the mic's native rate
    input_device: str = ""  # blank = Windows default mic; or a number / part of a name from `callout devices`
    decoys: list[str] = field(default_factory=list)  # extra near-miss words to hear and reject
    tts: bool = True
    voice_rate: int = 2  # spoken reply speed, -10 (slow) .. 10 (fast)
    voice_volume: int = 100  # 0 .. 100


@dataclass
class SafetyConfig:
    require_confirmation: bool = True
    confirm_timeout_s: float = 10.0
    confirm_flatten: bool = False
    flatten_cancels_all_orders: bool = False  # True = IBKR global cancel: EVERY open order in the account
    max_position: int = 2
    min_seconds_between_orders: float = 1.0
    max_orders_per_minute: int = 10
    check_market_hours: bool = True
    roll_days_before_expiry: int = 8


@dataclass
class Instrument:
    symbol: str
    enabled: bool = True
    exchange: str = "CME"
    currency: str = "USD"
    quantity: int = 1
    max_position: int | None = None  # overrides safety.max_position for this symbol
    spoken: list[str] = field(default_factory=list)  # phrases that mean this instrument
    say_as: str = ""  # how the app pronounces it in readbacks

    @property
    def label(self) -> str:
        return self.say_as or self.symbol


@dataclass
class Config:
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    instruments: dict[str, Instrument] = field(default_factory=dict)
    log_dir: str = "logs"

    @property
    def enabled_instruments(self) -> dict[str, Instrument]:
        return {s: i for s, i in self.instruments.items() if i.enabled}

    def max_position_for(self, symbol: str) -> int:
        inst = self.instruments[symbol]
        return inst.max_position if inst.max_position is not None else self.safety.max_position


DEFAULT_INSTRUMENTS = {
    "ES": Instrument(symbol="ES", spoken=["e s", "es", "e mini"], say_as="E S"),
    "MES": Instrument(
        symbol="MES", enabled=False, spoken=["micro e s", "micro es", "micro e mini"], say_as="micro E S"
    ),
}


def _build(cls, data: dict, section: str):
    allowed = set(cls.__dataclass_fields__)
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"[{section}] has unknown keys: {', '.join(sorted(unknown))}")
    return cls(**data)


def load_config(path: str | Path | None) -> Config:
    raw: dict = {}
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}")
        raw = tomllib.loads(p.read_text(encoding="utf-8"))

    cfg = Config(
        broker=_build(BrokerConfig, raw.get("broker", {}), "broker"),
        voice=_build(VoiceConfig, raw.get("voice", {}), "voice"),
        safety=_build(SafetyConfig, raw.get("safety", {}), "safety"),
        log_dir=raw.get("log_dir", "logs"),
    )

    inst_raw = raw.get("instruments")
    if inst_raw:
        for symbol, data in inst_raw.items():
            data = dict(data)
            data.setdefault("symbol", symbol.upper())
            cfg.instruments[symbol.upper()] = _build(Instrument, data, f"instruments.{symbol}")
    else:
        cfg.instruments = {k: Instrument(**vars(v)) for k, v in DEFAULT_INSTRUMENTS.items()}

    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    b, s, v = cfg.broker, cfg.safety, cfg.voice
    if b.type not in ("ibkr", "sim"):
        raise ConfigError("broker.type must be 'ibkr' or 'sim'")
    if b.trading_mode not in ("paper", "live"):
        raise ConfigError("broker.trading_mode must be 'paper' or 'live'")
    if b.trading_mode == "paper" and b.port in LIVE_PORTS:
        raise ConfigError(
            f"broker.port {b.port} is a LIVE port but trading_mode is 'paper'. "
            "Use 7497 (TWS paper) or 4002 (Gateway paper)."
        )
    if b.trading_mode == "live" and b.port in PAPER_PORTS:
        raise ConfigError(f"broker.port {b.port} is a PAPER port but trading_mode is 'live'.")
    if not cfg.enabled_instruments:
        raise ConfigError("No instruments are enabled.")
    for sym, inst in cfg.instruments.items():
        if inst.quantity < 1:
            raise ConfigError(f"instruments.{sym}.quantity must be >= 1")
        if inst.enabled and not inst.spoken:
            raise ConfigError(f"instruments.{sym} needs at least one 'spoken' phrase")
        if inst.quantity > cfg.max_position_for(sym):
            raise ConfigError(f"instruments.{sym}.quantity is larger than its max_position")
    if s.max_position < 1:
        raise ConfigError("safety.max_position must be >= 1")
    if not 0 <= v.min_confidence <= 1:
        raise ConfigError("voice.min_confidence must be between 0 and 1")


# ---- saving -------------------------------------------------------------------------------------

_SAVE_HEADER = (
    "# Callout settings. The app's Settings screen writes this file;\n"
    "# you can also edit it by hand while Callout is closed.\n\n"
)


def default_port(app: str, mode: str) -> int:
    """The standard port for 'tws' or 'gateway' with a 'paper' or 'live' account."""
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
    """Write cfg to path. Atomic on the same drive: a crash never leaves half a file."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_SAVE_HEADER + tomli_w.dumps(config_to_dict(cfg)), encoding="utf-8")
    tmp.replace(path)
