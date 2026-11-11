"""Trading in the console window, without the app window: python -m callout run."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid

from ..brokers import BrokerError, make_broker
from ..trading.engine import Engine, Meta
from ..trading.journal import Journal
from ..trading.risk import RiskManager
from ..voice.speaker import Speaker
from .common import audio_report, load_for, load_transcriber, make_talker, out, print_talk_state


async def run(args) -> int:
    cfg = load_for(args.config)
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
            transcriber = load_transcriber(cfg, engine.parser)

            def on_state(state: str) -> None:
                print_talk_state(state)
                if state == "too_short":  # an accidental tap still cancels a pending order
                    loop.call_soon_threadsafe(queue.put_nowait, ("reject", "too short", None))

            talker, hint = make_talker(
                cfg, lambda pcm, t: loop.call_soon_threadsafe(queue.put_nowait, ("audio", pcm, t)), on_state
            )
            talker.start()

        mode = "SIMULATED" if broker.name == "sim" else cfg.broker.trading_mode.upper()
        _print_banner(cfg, engine, risk, speaker, journal, account, mode, hint, args.ignore_market_hours)
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
                        rate = talker.recorder.sample_rate
                        tr = await loop.run_in_executor(None, transcriber.transcribe, payload, rate)
                        t_heard = time.monotonic()
                        out(
                            f"heard '{tr.text}' ({tr.confidence:.2f}, {(t_heard - t_release) * 1000:.0f} ms)"
                            f" | {audio_report(talker.recorder, payload)}"
                        )
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


def _print_banner(cfg, engine, risk, speaker, journal, account, mode, hint, hours_bypassed) -> None:
    out("-" * 60)
    out(f"Callout ready | {mode} | account {account}")
    for sym, c in engine.contracts.items():
        out(f"  {sym} -> {c.local_symbol}  qty {cfg.instruments[sym].quantity}  max {cfg.max_position_for(sym)}")
    out(
        f"  confirmation {'ON' if cfg.safety.require_confirmation else 'OFF'}"
        f" | market {'open' if risk.market_open() else 'CLOSED'}"
        f"{' (hours check bypassed)' if hours_bypassed else ''}"
    )
    out(f"  speech: {speaker.backend}" + (f" ({speaker.error})" if speaker.error else ""))
    out(f"  log: {journal.dir.resolve()}")
    out(hint)
    out("-" * 60)


def _stdin_lines(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    while True:
        try:
            line = input()
        except EOFError:
            loop.call_soon_threadsafe(queue.put_nowait, ("quit", None, None))
            return
        loop.call_soon_threadsafe(queue.put_nowait, ("text", line, None))


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
