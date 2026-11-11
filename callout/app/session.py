"""Runs Callout behind the desktop window.

The engine, broker and voice run on a background asyncio loop. The window
talks to this class only through a few thread-safe methods, and reads one
snapshot dict that a background task refreshes several times a second.
Every order still goes through the same Engine path as the console version:
on-screen buttons send the same "confirm", "cancel" and "flatten" commands
your voice does.
"""

from __future__ import annotations

import asyncio
import copy
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..brokers import BrokerError, make_broker
from ..config import Config, ConfigError, default_port, save_config
from ..trading.contracts import describe_position
from ..trading.engine import Engine, Meta
from ..trading.journal import Journal
from ..trading.market_hours import ET, market_status_text
from ..trading.risk import RiskManager
from ..voice.speaker import Speaker
from .activity import feed_row, pretty_intent
from .settings import apply_patch, settings_view

SNAPSHOT_EVERY_S = 0.15
FEED_ROWS = 120


class UIJournal(Journal):
    """Writes the log file as usual and also hands every record to the session."""

    def __init__(self, log_dir, session_id, on_record):
        super().__init__(log_dir, session_id)
        self._on_record = on_record

    def log(self, event: str, **fields: Any) -> dict:
        rec = super().log(event, **fields)
        try:
            self._on_record(rec)
        except Exception:
            pass
        return rec


class UISpeaker(Speaker):
    """Speaks as usual and also tells the session what was said, for the screen."""

    def __init__(self, on_say, **kw):
        self._on_say = on_say
        super().__init__(**kw)

    def say(self, text: str, interrupt: bool = False) -> None:
        try:
            self._on_say(text)
        except Exception:
            pass
        super().say(text, interrupt)


# What each kind of record means for the big order area on screen.
_LAST_KIND = {
    "awaiting_confirm": "pending",
    "blocked": "blocked",
    "flatten_incomplete": "blocked",
    "error": "blocked",
    "position_mismatch": "blocked",
}


class Session:
    def __init__(
        self,
        cfg: Config,
        config_path: str | Path,
        *,
        use_sim: bool = False,
        audio: bool = True,
        tts: bool = True,
        first_run: bool = False,
    ):
        self.cfg = cfg
        self.config_path = Path(config_path)
        self.use_sim = use_sim
        self.audio = audio
        self.tts_allowed = tts
        self.first_run = first_run
        self.loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None
        self.engine: Engine | None = None
        self.broker = None
        self.speaker: Speaker | None = None
        self.journal: Journal | None = None
        self.risk: RiskManager | None = None
        self.transcriber = None
        self.talker = None
        self.feed: deque[dict] = deque(maxlen=FEED_ROWS)
        self.feed_version = 0
        self.heard: dict | None = None
        self.last: dict = {"kind": "idle", "text": ""}
        self._last_kind: str | None = None
        self.status = {"voice": "starting", "voice_error": "", "broker_error": "", "connecting": False}
        # Live trading needs the person to type LIVE in this run of the app, like start-live.bat.
        self.live_unlocked = cfg.broker.trading_mode != "live"
        self.test_mode = False
        self.test_result: dict | None = None
        self.leftover = 0  # orders still working after a flatten Callout couldn't cancel
        self._working_fresh: int | None = None
        self._last_working = 0
        self._snapshot: dict = {"ready": False}
        self._queue: asyncio.Queue | None = None
        self._ever_connected = False
        self._clock_cache = (0.0, (False, ""))
        self._booted = threading.Event()

    # ---- lifecycle --------------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, name="callout-engine", daemon=True)
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._boot(), self.loop)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def wait_ready(self, timeout: float = 15) -> bool:
        return self._booted.wait(timeout)

    def stop(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop).result(timeout=8)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)

    async def _boot(self) -> None:
        cfg = self.cfg
        self._queue = asyncio.Queue()
        self.journal = UIJournal(cfg.log_dir, uuid.uuid4().hex[:8], self._on_record)
        self.speaker = UISpeaker(
            self._on_say,
            enabled=cfg.voice.tts and self.tts_allowed,
            echo=lambda s: None,
            rate=cfg.voice.voice_rate,
            volume=cfg.voice.voice_volume,
        )
        self.risk = RiskManager(cfg)
        self.broker = self._make_broker()
        self.engine = Engine(cfg, self.broker, self.speaker, self.journal, self.risk)
        self._tasks = [
            asyncio.create_task(c)
            for c in (self._snapshot_loop(), self._consume(), self._watchdog(), self._orders_loop())
        ]
        self._booted.set()
        if self.live_unlocked:
            await self._connect()
        if self.audio:
            await self._start_voice()
        else:
            self.status["voice"] = "off"

    async def _shutdown(self) -> None:
        for t in getattr(self, "_tasks", []):
            t.cancel()
        await asyncio.gather(*getattr(self, "_tasks", []), return_exceptions=True)
        if self.talker:
            try:
                self.talker.stop()
            except Exception:
                pass
        if self.journal:
            self.journal.log("shutdown")
        if self.speaker:
            self.speaker.close()
        if self.broker:
            await self.broker.disconnect()

    # ---- broker -------------------------------------------------------------------------------

    def _make_broker(self):
        return make_broker(
            self.cfg, use_sim=self.use_sim, allow_live=self.live_unlocked, on_event=self._on_broker_event
        )

    def _on_broker_event(self, kind: str, data: dict) -> None:
        self.journal.log(kind, **data)
        if kind == "disconnected":
            self.speaker.say("Lost connection to the broker.", True)

    async def _connect(self) -> None:
        self.status["connecting"] = True
        try:
            await self.engine.start()
            self.status["broker_error"] = ""
            self.speaker.say("Reconnected." if self._ever_connected else "Ready.")
            self._ever_connected = True
        except BrokerError as e:
            self.status["broker_error"] = str(e)
            self.journal.log("connect_failed", error=str(e))
        except Exception as e:
            self.status["broker_error"] = f"Unexpected error: {e}"
            self.journal.log("connect_failed", error=repr(e))
        finally:
            self.status["connecting"] = False

    async def _reconnect(self) -> None:
        async with self.engine._lock:  # never swap brokers in the middle of an order
            try:
                await self.broker.disconnect()
            except Exception:
                pass
            self.broker = self._make_broker()
            self.engine.broker = self.broker
            self.engine.contracts = {}
            self.engine.pending = None
        if self.live_unlocked:
            await self._connect()

    async def _watchdog(self) -> None:
        last_refresh = time.monotonic()
        while True:
            await asyncio.sleep(5)
            try:
                if not self.live_unlocked or self.status["connecting"]:
                    continue
                if not self.broker.connected:
                    await self._connect()
                elif time.monotonic() - last_refresh > 300:
                    last_refresh = time.monotonic()
                    await self.engine.refresh_contracts()
            except Exception as e:
                self.journal.log("error", error=f"watchdog: {e!r}")

    # ---- voice --------------------------------------------------------------------------------

    async def _start_voice(self) -> None:
        from ..voice.recognizer import Transcriber

        self.status.update(voice="loading", voice_error="")
        loop = asyncio.get_running_loop()
        try:
            if self.transcriber is None:
                cfg = self.cfg
                self.transcriber = await loop.run_in_executor(
                    None, lambda: Transcriber(cfg.voice.model, self.engine.parser.grammar, cfg.voice.sample_rate)
                )
            await loop.run_in_executor(None, self._start_talker_sync)
            self.status["voice"] = "ready"
        except Exception as e:
            self.status.update(voice="error", voice_error=str(e))

    def _start_talker_sync(self) -> None:
        from ..voice.microphone import Recorder, resolve_input_device
        from ..voice.push_to_talk import PushToTalk

        if self.talker:
            try:
                self.talker.stop()
            except Exception:
                pass
            self.talker = None
        cfg = self.cfg.voice
        rec = Recorder(cfg.sample_rate, device=resolve_input_device(cfg.input_device))
        try:
            talker = PushToTalk(rec, cfg.push_to_talk, self._on_utterance, self._on_talk_state)
        except ValueError as e:  # unknown key name: keep the on-screen button working
            talker = PushToTalk(rec, None, self._on_utterance, self._on_talk_state)
            self.status["voice_error"] = f"{e} The on-screen Talk button still works."
        try:
            talker.start()
        except Exception as e:  # global hotkeys unavailable: fall back to the on-screen button
            if talker.key is None:
                raise
            talker = PushToTalk(rec, None, self._on_utterance, self._on_talk_state)
            talker.start()
            self.status["voice_error"] = f"Talk key unavailable ({e}). Use the on-screen Talk button."
        self.talker = talker

    def _on_utterance(self, pcm: bytes, t_release: float) -> None:  # audio thread
        self.loop.call_soon_threadsafe(self._queue.put_nowait, ("audio", pcm, t_release))

    def _on_talk_state(self, state: str) -> None:  # audio thread
        if state == "too_short":
            self.loop.call_soon_threadsafe(self._queue.put_nowait, ("reject", None, None))

    async def _consume(self) -> None:
        from ..voice.microphone import audio_level

        loop = asyncio.get_running_loop()
        while True:
            kind, payload, t_release = await self._queue.get()
            try:
                if kind == "reject":
                    if not self.test_mode:
                        await self.engine.reject_input("too short", said="Too short.")
                    continue
                rate = self.talker.recorder.sample_rate if self.talker else self.cfg.voice.sample_rate
                tr = await loop.run_in_executor(None, self.transcriber.transcribe, payload, rate)
                t_heard = time.monotonic()
                self.heard = {
                    "text": tr.text,
                    "confidence": round(tr.confidence, 2),
                    "ms": round((t_heard - t_release) * 1000),
                    "level": round(audio_level(payload), 2),
                }
                if self.test_mode:
                    self.test_mode = False
                    intent = None if tr.has_unknown else self.engine.parser.parse(tr.text)
                    ok = intent is not None and tr.confidence >= self.cfg.voice.min_confidence
                    self.test_result = {
                        **self.heard,
                        "ok": ok,
                        "intent": pretty_intent(intent.describe()) if ok else None,
                    }
                    continue
                await self.engine.handle_transcript(tr, Meta(source="voice", t_release=t_release, t_heard=t_heard))
            except Exception as e:  # keep listening no matter what; flatten must stay available
                self.journal.log("error", error=repr(e))
                self.speaker.say("Something went wrong. Check your platform.", True)

    # ---- what the screen shows ------------------------------------------------------------------

    def _on_record(self, rec: dict) -> None:
        ev = rec.get("event")
        if ev in _LAST_KIND:
            self._last_kind = _LAST_KIND[ev]
        elif ev == "order_result":
            self._last_kind = "filled" if rec.get("status") == "Filled" else "blocked"
        elif ev == "heard" and (rec.get("rejected") or not rec.get("intent")):
            self._last_kind = "rejected"
        elif ev == "cancelled" and rec.get("by") != "new_command":
            self._last_kind = "cancelled"
        elif ev == "flatten_result":
            n = int(rec.get("still_working") or 0)
            self.leftover = n
            self._working_fresh = n
            self._last_working = n
            if n:
                self._last_kind = "flat_warn"
            elif not rec.get("ok"):
                self._last_kind = "blocked"
            elif rec.get("closed"):
                self._last_kind = "filled"
        row = feed_row(rec)
        if row:
            self.feed.appendleft(row)
            self.feed_version += 1

    def _on_say(self, text: str) -> None:
        self.last = {"kind": self._last_kind or "info", "text": text}
        if self._last_kind == "flat_warn":
            self.last["working"] = self._last_working
        self._last_kind = None

    async def _orders_loop(self) -> None:
        """Ask TWS for a fresh working-order count every few seconds. Manual TWS orders don't send
        Callout status updates, so this is how the screen notices when one is cancelled."""
        while True:
            await asyncio.sleep(1.0 if self.leftover else 3.0)
            try:
                if self.engine and self.broker and self.broker.connected:
                    n = await asyncio.wait_for(self.engine.working_orders(), 12)
                    if n is not None:
                        self._working_fresh = n
                        if self.leftover:
                            self.leftover = n
                else:
                    self._working_fresh = None
            except Exception:
                pass

    def _market(self) -> tuple[bool, str]:
        now = time.monotonic()
        if now - self._clock_cache[0] > 20:
            self._clock_cache = (now, market_status_text(datetime.now(ET)))
        is_open, text = self._clock_cache[1]
        if self.risk and not self.risk.market_open():
            is_open = False
        return is_open, text

    async def _snapshot_loop(self) -> None:
        while True:
            try:
                self._snapshot = await self._build_snapshot()
            except Exception as e:
                self._snapshot = {**self._snapshot, "snapshot_error": repr(e)}
            await asyncio.sleep(SNAPSHOT_EVERY_S)

    async def _build_snapshot(self) -> dict:
        cfg, eng, b = self.cfg, self.engine, self.broker
        connected = bool(b and b.connected)
        held = await b.positions(set(cfg.instruments)) if connected else []
        fronts = list(eng.contracts.values())
        instruments = []
        for sym, inst in cfg.enabled_instruments.items():
            front = eng.contracts.get(sym)
            qty = sum(q for c, q in held if front and c.same_contract(front))
            roll = None
            if front and front.expiry:
                d = front.expiry - timedelta(days=cfg.safety.roll_days_before_expiry)
                roll = f"{d:%b} {d.day}"
            instruments.append(
                {
                    "symbol": sym,
                    "label": inst.label,
                    "name": inst.say_as or sym,
                    "contract": front.local_symbol if front else None,
                    "roll": roll,
                    "qty": qty,
                    "position": describe_position(qty),
                    "avg": b.avg_price(front) if (connected and front and qty) else None,
                    "quantity": inst.quantity,
                    "max": cfg.max_position_for(sym),
                }
            )
        older = [
            {"contract": c.local_symbol, "position": describe_position(q)}
            for c, q in held
            if not any(c.same_contract(f) for f in fronts)
        ]
        account = eng.account if connected else ""
        if b is not None and b.name == "sim":
            badge = "SIM"
        elif connected:
            badge = "PAPER" if account.upper().startswith("D") else "LIVE"
        else:
            badge = cfg.broker.trading_mode.upper()
        market_open, market_text = self._market()
        talker = self.talker
        return {
            "ready": True,
            "connected": connected,
            "connecting": self.status["connecting"],
            "broker_error": self.status["broker_error"],
            "account": account,
            "badge": badge,
            "live_locked": not self.live_unlocked,
            "first_run": self.first_run,
            "market_open": market_open,
            "market_text": market_text,
            "instruments": instruments,
            "older": older,
            "working": (
                self._working_fresh if self._working_fresh is not None else b.working_count(set(cfg.instruments))
            )
            if connected
            else None,
            "leftover": self.leftover if connected and not held else 0,
            "pending": eng.pending_summary(),
            "last": self.last,
            "heard": self.heard,
            "listening": bool(talker and talker.listening),
            "level": round(talker.recorder.level, 3) if talker else 0.0,
            "mic": talker.recorder.device_name if talker else "",
            "hotkey": (cfg.voice.push_to_talk or "").upper() if talker and talker.key is not None else "",
            "voice": self.status["voice"],
            "voice_error": self.status["voice_error"],
            "confirm": cfg.safety.require_confirmation,
            "tts": cfg.voice.tts,
            "test_mode": self.test_mode,
            "test_result": self.test_result,
            "feed_version": self.feed_version,
        }

    # ---- thread-safe API used by the window -------------------------------------------------------

    def snapshot(self, feed_version: int = -1) -> dict:
        snap = dict(self._snapshot)
        if snap.get("feed_version", 0) != feed_version:
            snap["feed"] = list(self.feed)[:60]
        return snap

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def command(self, text: str) -> None:
        """Same path as speaking it: 'confirm', 'cancel', 'flatten', 'buy es'..."""
        if self.engine:
            self._submit(self.engine.handle_text(text, Meta(source="ui")))

    def talk(self, down: bool) -> None:
        if self.talker:
            (self.talker.begin if down else self.talker.end)()

    def start_test(self) -> None:
        self.test_result = None
        self.test_mode = True

    def say_sample(self) -> None:
        if self.speaker:
            self.speaker.say("Buy 1 E S. Flat to long 1. Say confirm.", True)

    def unlock_live(self, text: str) -> dict:
        if (text or "").strip() != "LIVE":
            return {"ok": False, "error": "Type LIVE in capitals to trade real money."}
        self.live_unlocked = True
        self._submit(self._reconnect())
        return {"ok": True}

    def apply(self, patch: dict) -> dict:
        return self._submit(self._apply(dict(patch))).result(timeout=30)

    def test_connection(self, app: str, mode: str, port: int | None = None, host: str | None = None) -> dict:
        return self._submit(self._test_connection(app, mode, port, host)).result(timeout=30)

    def finish_setup(self) -> None:
        save_config(self.cfg, self.config_path)
        self.first_run = False

    def settings(self) -> dict:
        return settings_view(self.cfg, self.use_sim)

    def mics(self) -> list[dict]:
        try:
            from ..voice.microphone import main_input_devices

            return [{"index": d["index"], "name": d["name"], "default": d["default"]} for d in main_input_devices()]
        except Exception:
            return []

    def open_logs(self) -> None:
        path = Path(self.cfg.log_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    # ---- settings ----------------------------------------------------------------------------------

    async def _apply(self, patch: dict) -> dict:
        cfg = self.cfg
        try:
            applied = apply_patch(cfg, patch, self.live_unlocked)
        except ConfigError as e:
            return {"ok": False, "error": str(e)}
        self.live_unlocked = applied.live_unlocked
        needs = applied.needs

        if self.speaker:
            self.speaker.set_enabled(cfg.voice.tts and self.tts_allowed)
            self.speaker.set_voice(rate=cfg.voice.voice_rate, volume=cfg.voice.voice_volume)
        save_config(cfg, self.config_path)
        warnings = []
        if "grammar" in needs:
            await self.engine.reconfigure()
            if self.transcriber is not None:
                try:
                    self.transcriber.set_phrases(self.engine.parser.grammar)
                except Exception as e:
                    warnings.append(str(e))
        if "talker" in needs and self.audio and self.transcriber is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._start_talker_sync)
            except Exception as e:
                self.status["voice_error"] = str(e)
                warnings.append(f"Microphone: {e}")
        if "connection" in needs:
            asyncio.create_task(self._reconnect())
        return {"ok": True, "warnings": warnings}

    async def _test_connection(self, app: str, mode: str, port, host) -> dict:
        port = int(port) if port not in (None, "") else default_port(app, mode)
        host = host or self.cfg.broker.host
        b0 = self.cfg.broker
        if self.broker and self.broker.connected and (b0.trading_mode, b0.port, b0.host) == (mode, port, host):
            first = next(iter(self.engine.contracts.values()), None)
            return {
                "ok": True,
                "account": self.engine.account,
                "badge": self._snapshot.get("badge", mode.upper()),
                "contract": first.local_symbol if first else None,
            }
        tmp = copy.deepcopy(self.cfg)
        tmp.broker.trading_mode, tmp.broker.port, tmp.broker.host = mode, port, host
        tmp.broker.client_id = self.cfg.broker.client_id + 50  # don't collide with the live session
        probe = make_broker(tmp, use_sim=self.use_sim, allow_live=True)
        try:
            account = await probe.connect()
            inst = next(iter(tmp.enabled_instruments.values()))
            c = await probe.front_month(inst, tmp.safety.roll_days_before_expiry)
            badge = "SIM" if probe.name == "sim" else ("PAPER" if account.upper().startswith("D") else "LIVE")
            return {"ok": True, "account": account, "badge": badge, "contract": c.local_symbol}
        except BrokerError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"Unexpected error: {e}"}
        finally:
            await probe.disconnect()
