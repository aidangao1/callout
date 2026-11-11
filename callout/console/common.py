"""Helpers shared by the console commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..config import Config, ConfigError, load_config
from ..trading.market_hours import ET
from ..voice.intents import IntentParser


def out(msg: str = "") -> None:
    """Print a line with an ET timestamp."""
    print(f"[{datetime.now(ET):%H:%M:%S}] {msg}" if msg else "", flush=True)


def load_for(config_path: str) -> Config:
    """Load the config a command was pointed at, or the defaults if there's no config.toml yet."""
    path = Path(config_path)
    if not path.exists():
        if config_path == "config.toml":
            out("No config.toml found, using defaults. Run `python -m callout init` to create one.")
            return load_config(None)
        raise ConfigError(f"Config file not found: {path}")
    return load_config(path)


def print_talk_state(state: str) -> None:
    messages = {
        "listening": "listening... (release to send)",
        "listening_enter": "listening... (press Enter to send)",
        "processing": "processing",
        "too_short": "too short, ignored",
    }
    out(messages.get(state, state))


def load_transcriber(cfg: Config, parser: IntentParser):
    from ..voice.recognizer import Transcriber

    out(f"Loading speech model '{cfg.voice.model}' (first run downloads ~40 MB)...")
    tr = Transcriber(cfg.voice.model, parser.grammar, cfg.voice.sample_rate)
    if tr.dropped:
        out(f"Note: these phrases use words the model doesn't know and were disabled: {', '.join(tr.dropped)}")
    return tr


def make_talker(cfg: Config, on_utterance, on_state=print_talk_state):
    """The mic plus push-to-talk (or Enter-to-talk), and a one-line hint on how to use it."""
    from ..voice.microphone import Recorder, resolve_input_device
    from ..voice.push_to_talk import EnterToTalk, PushToTalk

    rec = Recorder(cfg.voice.sample_rate, device=resolve_input_device(cfg.voice.input_device))
    out(f"Microphone: {rec.device_name} ({rec.sample_rate} Hz)")
    key = cfg.voice.push_to_talk
    if key.lower() == "enter":
        return EnterToTalk(rec, on_utterance, on_state), "Press Enter, speak, press Enter."
    return PushToTalk(rec, key, on_utterance, on_state), f"Hold {key.upper()} and speak."


def audio_report(rec, pcm: bytes) -> str:
    """'1.6s audio, level 37%', plus a hint when the mic looks silent or quiet."""
    from ..voice.microphone import audio_level

    secs, level = rec.seconds(pcm), audio_level(pcm)
    note = ""
    if rec.callbacks == 0:
        note = "  !! no audio is arriving from this mic at all"
    elif level < 0.02:
        note = (
            "  !! mic is silent: wrong mic, muted, or Windows is blocking mic access "
            "(Settings > Privacy & security > Microphone)"
        )
    elif level < 0.10:
        note = "  (quiet: speak up, move closer, or raise the mic level in Windows sound settings)"
    return f"{secs:.1f}s audio, level {level:.0%}{note}"
