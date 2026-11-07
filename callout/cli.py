"""Command line entry point: python -m callout <command>."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .brokers import BrokerError, make_broker
from .config import Config, ConfigError, load_config
from .contracts import describe_position
from .engine import Engine, Meta
from .intents import IntentParser
from .journal import Journal
from .risk import ET, RiskManager, cme_equity_index_open
from .tts import Speaker

TEMPLATE = Path(__file__).with_name("config_template.toml")


def out(msg: str = "") -> None:
    print(f"[{datetime.now(ET):%H:%M:%S}] {msg}" if msg else "", flush=True)


# ---- helpers ----------------------------------------------------------------------------------


def _load(args) -> Config:
    path = Path(args.config)
    if not path.exists():
        if args.config == "config.toml":
            out("No config.toml found, using defaults. Run `python -m callout init` to create one.")
            return load_config(None)
        raise ConfigError(f"Config file not found: {path}")
    return load_config(path)


def _on_state(state: str) -> None:
    messages = {
        "listening": "listening... (release to send)",
        "listening_enter": "listening... (press Enter to send)",
        "processing": "processing",
        "too_short": "too short, ignored",
    }
    out(messages.get(state, state))


def _load_transcriber(cfg: Config, parser: IntentParser):
    from .stt import Transcriber

    out(f"Loading speech model '{cfg.voice.model}' (first run downloads ~40 MB)...")
    tr = Transcriber(cfg.voice.model, parser.grammar, cfg.voice.sample_rate)
    if tr.dropped:
        out(f"Note: these phrases use words the model doesn't know and were disabled: {', '.join(tr.dropped)}")
    return tr


def _make_talker(cfg: Config, on_utterance, on_state=_on_state):
    from .audio import EnterToTalk, PushToTalk, Recorder, resolve_input_device

    rec = Recorder(cfg.voice.sample_rate, device=resolve_input_device(cfg.voice.input_device))
    out(f"Microphone: {rec.device_name} ({rec.sample_rate} Hz)")
    if cfg.voice.push_to_talk.lower() == "enter":
        return EnterToTalk(rec, on_utterance, on_state), "Press Enter, speak, press Enter."
    return PushToTalk(rec, cfg.voice.push_to_talk, on_utterance, on_state), f"Hold {cfg.voice.push_to_talk.upper()} and speak."


def _stdin_lines(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    while True:
        try:
            line = input()
        except EOFError:
            loop.call_soon_threadsafe(queue.put_nowait, ("quit", None, None))
            return
        loop.call_soon_threadsafe(queue.put_nowait, ("text", line, None))


# ---- commands ---------------------------------------------------------------------------------


def cmd_init(args) -> int:
    dest = Path(args.config)
    if dest.exists() and not args.force:
        out(f"{dest} already exists (use --force to overwrite).")
        return 1
    shutil.copyfile(TEMPLATE, dest)
    out(f"Wrote {dest}. Edit it, then run: python -m callout check")
    return 0


async def cmd_check(args) -> int:
    cfg = _load(args)
    broker = make_broker(cfg, use_sim=args.sim, allow_live=args.live)
    try:
        account = await broker.connect()
        out(f"Connected to {broker.name}. Account {account} ({cfg.broker.trading_mode}).")
        for sym, inst in cfg.enabled_instruments.items():
            c = await broker.front_month(inst, cfg.safety.roll_days_before_expiry)
            pos = await broker.position(c)
            out(f"  {sym}: trading {c.local_symbol} (expires {c.expiry}), position {describe_position(pos)}")
        others = await broker.positions(set(cfg.enabled_instruments))
        for c, q in others:
            out(f"  holding {describe_position(q)} {c.local_symbol}")
        out(f"CME equity-index market open now: {'yes' if cme_equity_index_open(datetime.now(ET)) else 'no'}")
        return 0
    except BrokerError as e:
        out(f"ERROR: {e}")
        return 2
    finally:
        await broker.disconnect()


def cmd_devices(args) -> int:
    from .audio import list_input_devices

    devices = list_input_devices()
    if not devices:
        out("No microphones found.")
        return 1
    out("Microphones (set voice.input_device in config.toml to the number or part of the name):")
    for d in devices:
        mark = "  <- default" if d["default"] else ""
        out(f"  {d['index']:>3}  {d['name']}  [{d['hostapi']}, {d['rate']} Hz]{mark}")
    return 0


def cmd_tts_test(args) -> int:
    speaker = Speaker(enabled=True, echo=out)
    out(f"Speech engine: {speaker.backend}" + (f" ({speaker.error})" if speaker.error else ""))
    speaker.say("Callout speech test. Buy 1 E S. Flat to long 1. Say confirm.")
    speaker.close(wait=True)
    if speaker.backend in ("none", "off") or speaker.error:
        out("No speech. Check the error above, and that Windows' default playback device is the one you're listening on.")
        return 1
    out("If you heard nothing, Windows is playing it on a different output device: "
        "check Settings > System > Sound > Output.")
    return 0


def cmd_mic_scan(args) -> int:
    """Record a moment from every mic so you can see which one actually hears you."""
    from .audio import audio_level, list_input_devices, sample_device

    devices = [d for d in list_input_devices() if args.all or "WDM-KS" not in d["hostapi"]]
    out(f"Scanning {len(devices)} mic entries, about 2 seconds each.")
    out("Start counting out loud now and keep going until it says done.")
    time.sleep(1.5)
    best = None
    for d in devices:
        label = f"{d['index']:>3}  {d['name'][:40]:<40} [{d['hostapi']}]"
        try:
            pcm, blocks = sample_device(d["index"], d["rate"])
        except Exception as e:
            out(f"{label}  could not open: {str(e)[:70]}")
            continue
        level = audio_level(pcm)
        bar = "#" * round(level * 30)
        note = "  no audio arriving" if blocks == 0 else ""
        out(f"{label}  {level:>4.0%} {bar}{note}")
        if blocks and (best is None or level > best[1]):
            best = (d, level)
    out("Done. You can stop talking.")
    if best and best[1] >= 0.05:
        out(f'Loudest: {best[0]["index"]} ({best[0]["name"]}). Put input_device = "{best[0]["index"]}" under [voice] in config.toml.')
    else:
        out("Every mic is silent. Windows is still blocking mic access for this app, or another program "
            "has exclusive control of the mic.")
    return 0


def _audio_report(rec, pcm: bytes) -> str:
    from .audio import audio_level

    secs, level = rec.seconds(pcm), audio_level(pcm)
    note = ""
    if rec.callbacks == 0:
        note = "  !! no audio is arriving from this mic at all"
    elif level < 0.02:
        note = ("  !! mic is silent: wrong mic, muted, or Windows is blocking mic access "
                "(Settings > Privacy & security > Microphone)")
    elif level < 0.10:
        note = "  (quiet: speak up, move closer, or raise the mic level in Windows sound settings)"
    return f"{secs:.1f}s audio, level {level:.0%}{note}"


async def cmd_mic_test(args) -> int:
    """Talk to it without any broker: see exactly what it hears and how it would act."""
    cfg = _load(args)
    parser = IntentParser(cfg)
    transcriber = _load_transcriber(cfg, parser)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    talker, hint = _make_talker(cfg, lambda pcm, t: loop.call_soon_threadsafe(queue.put_nowait, (pcm, t)))
    talker.start()
    try:
        from .audio import main_input_devices

        others = [d for d in main_input_devices() if d["name"] != talker.recorder.device_name]
        if others:
            out("Other microphones: " + "; ".join(f"{d['index']} = {d['name']}" for d in others))
            out('  To use one, put its number in config.toml under [voice], e.g. input_device = "2"')
    except Exception:
        pass
    out(f"Mic test. {hint} Nothing is traded. Close the window or press Ctrl+C to quit.")
    out("Commands: " + ", ".join(sorted(parser.phrases)))
    out("Also try things that AREN'T commands (\"flat\", \"yes\", a cough): they should all say REJECT.")
    try:
        while True:
            pcm, t_release = await queue.get()
            tr = await loop.run_in_executor(None, transcriber.transcribe, pcm, talker.recorder.sample_rate)
            ms = (time.monotonic() - t_release) * 1000
            intent = parser.parse(tr.text) if not tr.has_unknown else None
            ok = intent and tr.confidence >= cfg.voice.min_confidence
            verdict = f"would do: {intent.describe()}" if ok else "would REJECT"
            out(f"heard '{tr.text}'  confidence {tr.confidence:.2f}  ({ms:.0f} ms)  -> {verdict}")
            out(f"    {_audio_report(talker.recorder, pcm)}")
    finally:
        talker.stop()


async def cmd_run(args) -> int:
    cfg = _load(args)
    if args.sim:
        cfg.broker.type = "sim"
    if args.ignore_market_hours and cfg.broker.trading_mode == "live" and cfg.broker.type != "sim":
        out("ERROR: --ignore-market-hours is only allowed with paper or sim.")
        return 2

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    journal = Journal(cfg.log_dir, session=uuid.uuid4().hex[:8])
    speaker = Speaker(enabled=cfg.voice.tts and not args.mute, echo=out)

    def on_broker_event(kind: str, data: dict) -> None:
        journal.log(kind, **data)
        if kind == "disconnected":
            loop.call_soon_threadsafe(speaker.say, "Lost connection to the broker.", True)
        elif kind == "broker_error":
            out(f"broker: [{data.get('code')}] {data.get('message')}")

    broker = make_broker(cfg, use_sim=args.sim, allow_live=args.live, on_event=on_broker_event)
    risk = RiskManager(cfg)
    risk.ignore_market_hours = args.ignore_market_hours
    engine = Engine(cfg, broker, speaker, journal, risk)

    try:
        account = await engine.start()
    except BrokerError as e:
        out(f"ERROR: {e}")
        return 2

    talker = None
    transcriber = None
    try:
        if args.text:
            threading.Thread(target=_stdin_lines, args=(loop, queue), daemon=True).start()
            hint = "Type commands (e.g. 'buy es', 'confirm', 'flatten'). 'quit' to exit."
        else:
            transcriber = _load_transcriber(cfg, engine.parser)

            def on_state(state: str) -> None:
                _on_state(state)
                if state == "too_short":  # an accidental tap still cancels a pending order
                    loop.call_soon_threadsafe(queue.put_nowait, ("reject", "too short", None))

            talker, hint = _make_talker(
                cfg, lambda pcm, t: loop.call_soon_threadsafe(queue.put_nowait, ("audio", pcm, t)), on_state
            )
            talker.start()

        mode = "SIMULATED" if broker.name == "sim" else cfg.broker.trading_mode.upper()
        out("-" * 60)
        out(f"Callout ready | {mode} | account {account}")
        for sym, c in engine.contracts.items():
            out(f"  {sym} -> {c.local_symbol}  qty {cfg.instruments[sym].quantity}  max {cfg.max_position_for(sym)}")
        out(f"  confirmation {'ON' if cfg.safety.require_confirmation else 'OFF'}"
            f" | market {'open' if risk.market_open() else 'CLOSED'}"
            f"{' (hours check bypassed)' if args.ignore_market_hours else ''}")
        out(f"  speech: {speaker.backend}" + (f" ({speaker.error})" if speaker.error else ""))
        out(f"  log: {journal.dir.resolve()}")
        out(hint)
        out("-" * 60)
        if mode == "LIVE":
            speaker.say("Warning. Live trading.")
        speaker.say("Ready.")

        watchdog = asyncio.create_task(_watchdog(engine, broker, speaker))
        try:
            while True:
                kind, payload, t_release = await queue.get()
                if kind == "quit" or (kind == "text" and payload.strip().lower() in ("quit", "exit")):
                    break
                try:
                    if kind == "text":
                        if payload.strip():
                            await engine.handle_text(payload, Meta(source="text"))
                    elif kind == "reject":
                        await engine.reject_input(payload, said="Too short.")
                    else:
                        tr = await loop.run_in_executor(
                            None, transcriber.transcribe, payload, talker.recorder.sample_rate
                        )
                        t_heard = time.monotonic()
                        out(f"heard '{tr.text}' ({tr.confidence:.2f}, {(t_heard - t_release) * 1000:.0f} ms)"
                            f" | {_audio_report(talker.recorder, payload)}")
                        await engine.handle_transcript(tr, Meta(source="voice", t_release=t_release, t_heard=t_heard))
                except Exception as e:  # keep listening no matter what; flatten must stay available
                    journal.log("error", error=repr(e))
                    speaker.say("Something went wrong. Check your platform.", True)
        finally:
            watchdog.cancel()
    finally:
        if talker:
            talker.stop()
        journal.log("shutdown")
        speaker.close()
        await broker.disconnect()
    return 0


async def _watchdog(engine: Engine, broker, speaker: Speaker) -> None:
    """Reconnects after drops and keeps the front-month contract current.

    Both go through the engine's lock, so they never interleave with a command.
    """
    last_refresh = time.monotonic()
    while True:
        await asyncio.sleep(5)
        if not broker.connected:
            try:
                await engine.start()
                speaker.say("Reconnected.")
            except Exception as e:  # keep trying quietly
                engine.journal.log("reconnect_failed", error=str(e))
                continue
        if time.monotonic() - last_refresh > 300:
            last_refresh = time.monotonic()
            try:
                await engine.refresh_contracts()
            except Exception as e:
                engine.journal.log("refresh_failed", error=str(e))


# ---- argument parsing -------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="callout", description="Voice-command order entry for IBKR futures.")
    p.add_argument("--config", default="config.toml", help="path to config file (default: config.toml)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="write a starter config.toml")
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("check", help="connect to the broker, show contracts and positions, then exit")
    s.add_argument("--sim", action="store_true")
    s.add_argument("--live", action="store_true")

    sub.add_parser("devices", help="list microphones")
    sub.add_parser("tts-test", help="speak a test sentence")
    s = sub.add_parser("mic-scan", help="record a moment from every mic and show which one hears you")
    s.add_argument("--all", action="store_true", help="include WDM-KS entries")
    sub.add_parser("mic-test", help="speak commands and see what's recognised; never trades")

    s = sub.add_parser("run", help="start trading")
    s.add_argument("--sim", action="store_true", help="simulated broker, no TWS needed")
    s.add_argument("--text", action="store_true", help="type commands instead of speaking")
    s.add_argument("--live", action="store_true", help="required (with trading_mode = 'live') for real money")
    s.add_argument("--mute", action="store_true", help="no spoken readback")
    s.add_argument("--ignore-market-hours", action="store_true", help="paper/sim only: skip the hours check")

    args = p.parse_args(argv)
    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "devices":
            return cmd_devices(args)
        if args.command == "tts-test":
            return cmd_tts_test(args)
        if args.command == "mic-scan":
            return cmd_mic_scan(args)
        handler = {"check": cmd_check, "mic-test": cmd_mic_test, "run": cmd_run}[args.command]
        return asyncio.run(handler(args))
    except ConfigError as e:
        out(f"Config error: {e}")
        return 2
    except KeyboardInterrupt:
        out("Stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
