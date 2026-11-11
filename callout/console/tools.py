"""Setup and troubleshooting commands: init, check, devices, tts-test, mic-scan, mic-test."""

from __future__ import annotations

import asyncio
import shutil
import time
from datetime import datetime
from pathlib import Path

from ..brokers import BrokerError, make_broker
from ..config import TEMPLATE
from ..trading.contracts import describe_position
from ..trading.market_hours import ET, cme_equity_index_open
from ..voice.intents import IntentParser
from ..voice.speaker import Speaker
from .common import audio_report, load_for, load_transcriber, make_talker, out


def init(args) -> int:
    """Write a starter config.toml."""
    dest = Path(args.config)
    if dest.exists() and not args.force:
        out(f"{dest} already exists (use --force to overwrite).")
        return 1
    shutil.copyfile(TEMPLATE, dest)
    out(f"Wrote {dest}. Edit it, then run: python -m callout check")
    return 0


async def check(args) -> int:
    """Connect, show the contract Callout would trade and the positions held, then exit."""
    cfg = load_for(args.config)
    broker = make_broker(cfg, use_sim=args.sim, allow_live=args.live)
    try:
        account = await broker.connect()
        out(f"Connected to {broker.name}. Account {account} ({cfg.broker.trading_mode}).")
        for sym, inst in cfg.enabled_instruments.items():
            c = await broker.front_month(inst, cfg.safety.roll_days_before_expiry)
            pos = await broker.position(c)
            out(f"  {sym}: trading {c.local_symbol} (expires {c.expiry}), position {describe_position(pos)}")
        for c, q in await broker.positions(set(cfg.enabled_instruments)):
            out(f"  holding {describe_position(q)} {c.local_symbol}")
        out(f"CME equity-index market open now: {'yes' if cme_equity_index_open(datetime.now(ET)) else 'no'}")
        return 0
    except BrokerError as e:
        out(f"ERROR: {e}")
        return 2
    finally:
        await broker.disconnect()


def devices(args) -> int:
    """List microphones."""
    from ..voice.microphone import list_input_devices

    found = list_input_devices()
    if not found:
        out("No microphones found.")
        return 1
    out("Microphones (set voice.input_device in config.toml to the number or part of the name):")
    for d in found:
        mark = "  <- default" if d["default"] else ""
        out(f"  {d['index']:>3}  {d['name']}  [{d['hostapi']}, {d['rate']} Hz]{mark}")
    return 0


def tts_test(args) -> int:
    """Speak a test sentence."""
    speaker = Speaker(enabled=True, echo=out)
    out(f"Speech engine: {speaker.backend}" + (f" ({speaker.error})" if speaker.error else ""))
    speaker.say("Callout speech test. Buy 1 E S. Flat to long 1. Say confirm.")
    speaker.close(wait=True)
    if speaker.backend in ("none", "off") or speaker.error:
        out("No speech. Check the error above, and that Windows' default playback device is the one you use.")
        return 1
    out("If you heard nothing, Windows is playing it on another output: check Settings > System > Sound > Output.")
    return 0


def mic_scan(args) -> int:
    """Record a moment from every mic so you can see which one actually hears you."""
    from ..voice.microphone import audio_level, list_input_devices, sample_device

    mics = [d for d in list_input_devices() if args.all or "WDM-KS" not in d["hostapi"]]
    out(f"Scanning {len(mics)} mic entries, about 2 seconds each.")
    out("Start counting out loud now and keep going until it says done.")
    time.sleep(1.5)
    best = None
    for d in mics:
        label = f"{d['index']:>3}  {d['name'][:40]:<40} [{d['hostapi']}]"
        try:
            pcm, blocks = sample_device(d["index"], d["rate"])
        except Exception as e:
            out(f"{label}  could not open: {str(e)[:70]}")
            continue
        level = audio_level(pcm)
        note = "  no audio arriving" if blocks == 0 else ""
        out(f"{label}  {level:>4.0%} {'#' * round(level * 30)}{note}")
        if blocks and (best is None or level > best[1]):
            best = (d, level)
    out("Done. You can stop talking.")
    if best and best[1] >= 0.05:
        d = best[0]
        out(f'Loudest: {d["index"]} ({d["name"]}). Put input_device = "{d["index"]}" under [voice] in config.toml.')
    else:
        out(
            "Every mic is silent. Windows is still blocking mic access for this app, "
            "or another program has exclusive control of the mic."
        )
    return 0


async def mic_test(args) -> int:
    """Speak commands and see exactly what's heard and what Callout would do. Never trades."""
    cfg = load_for(args.config)
    parser = IntentParser(cfg)
    transcriber = load_transcriber(cfg, parser)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    talker, hint = make_talker(cfg, lambda pcm, t: loop.call_soon_threadsafe(queue.put_nowait, (pcm, t)))
    talker.start()
    try:
        from ..voice.microphone import main_input_devices

        others = [d for d in main_input_devices() if d["name"] != talker.recorder.device_name]
        if others:
            out("Other microphones: " + "; ".join(f"{d['index']} = {d['name']}" for d in others))
            out('  To use one, put its number in config.toml under [voice], e.g. input_device = "2"')
    except Exception:
        pass
    out(f"Mic test. {hint} Nothing is traded. Close the window or press Ctrl+C to quit.")
    out("Commands: " + ", ".join(sorted(parser.phrases)))
    out('Also try things that AREN\'T commands ("flat", "yes", a cough): they should all say REJECT.')
    try:
        while True:
            pcm, t_release = await queue.get()
            tr = await loop.run_in_executor(None, transcriber.transcribe, pcm, talker.recorder.sample_rate)
            ms = (time.monotonic() - t_release) * 1000
            intent = parser.parse(tr.text) if not tr.has_unknown else None
            ok = intent and tr.confidence >= cfg.voice.min_confidence
            verdict = f"would do: {intent.describe()}" if ok else "would REJECT"
            out(f"heard '{tr.text}'  confidence {tr.confidence:.2f}  ({ms:.0f} ms)  -> {verdict}")
            out(f"    {audio_report(talker.recorder, pcm)}")
    finally:
        talker.stop()
