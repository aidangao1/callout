"""The phone link: pairing, encryption, the wake word, and a full round trip through a relay."""

import asyncio
import os
import threading
import time

import pytest
from fake_relay import FakeRelay

from callout.app.session import Session
from callout.config import load_config
from callout.remote.phone_protocol import Channel, Pairing, ProtocolError, pcm_to_b64
from callout.remote.wake import WAKE, phone_grammar, route
from callout.voice.intents import IntentParser
from callout.voice.recognizer import Transcript


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


# ---- pairing and encryption --------------------------------------------------------------------


def test_pairing_link_round_trip_keeps_the_key_out_of_the_url_path():
    p = Pairing.new("https://relay.example.workers.dev/")
    link = p.link()
    assert link.startswith("https://relay.example.workers.dev/pair#")  # key only after '#': never sent to servers
    assert Pairing.from_link(link) == p
    assert p.socket_url("pc") == f"wss://relay.example.workers.dev/room/{p.room}?role=pc"
    with pytest.raises(ProtocolError):
        Pairing.from_link("https://relay.example.workers.dev/pair#r=short")


def test_frames_are_sealed_and_checked():
    p = Pairing.new("https://relay.example")
    pc, phone = Channel(p, "pc"), Channel(p, "phone")
    frame = phone.seal("cmd", text="confirm")
    assert b"confirm" not in frame  # the relay only sees ciphertext
    assert pc.open(frame)["text"] == "confirm"
    with pytest.raises(ProtocolError, match="repeated"):
        pc.open(frame)  # a captured "confirm" can't be replayed
    with pytest.raises(ProtocolError, match="decrypted"):
        pc.open(Channel(Pairing.new("https://relay.example"), "phone").seal("cmd", text="buy es"))  # wrong key
    with pytest.raises(ProtocolError, match="wrong side"):
        pc.open(Channel(p, "pc").seal("cmd", text="buy es"))  # the PC's own frame bounced back
    old = Channel(p, "phone", clock=lambda: time.time() - 600).seal("cmd", text="confirm")
    with pytest.raises(ProtocolError, match="too old"):
        pc.open(old)


# ---- the wake word -----------------------------------------------------------------------------


def test_only_wake_word_commands_count_except_confirm_while_waiting():
    assert route(f"{WAKE} buy e s", False, pending=False) == ("command", "buy e s")
    assert route("callout flatten", False, pending=False) == ("command", "flatten")
    assert route("buy e s", False, pending=False) == ("ignore", "no wake word")  # someone else talking
    assert route(WAKE, False, pending=False) == ("ignore", "wake word only")
    assert route("confirm", False, pending=False) == ("ignore", "no wake word")
    assert route("confirm", False, pending=True) == ("command", "confirm")
    assert route("confirm", True, pending=True)[0] == "ignore"
    assert route("", False, pending=True) == ("ignore", "silence")


def test_phone_grammar_has_woken_commands_and_bare_replies():
    g = phone_grammar(IntentParser(load_config(None)))
    assert f"{WAKE} buy e s" in g and f"{WAKE} flatten" in g and "confirm" in g and "cancel" in g
    assert "buy e s" not in g  # without the wake word it can't be heard as a command at all


# ---- a full round trip -------------------------------------------------------------------------


class Loop:
    """An asyncio loop on its own thread, for the relay and the fake phone."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout=5):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class FakePhone:
    """Plays the phone app's part: same protocol, same relay."""

    def __init__(self, pairing: Pairing, key_override: bytes | None = None):
        p = Pairing(pairing.relay, pairing.room, key_override) if key_override else pairing
        self.pairing, self.ch = pairing, Channel(p, "phone")
        self.got: list[dict] = []
        self.ws = None

    async def connect(self):
        from websockets.asyncio.client import connect

        self.ws = await connect(self.pairing.socket_url("phone"))
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        listener = Channel(self.pairing, "phone")  # opens frames from the PC
        async for frame in self.ws:
            if isinstance(frame, bytes):
                self.got.append(listener.open(frame))

    async def send(self, kind, **payload):
        await self.ws.send(self.ch.seal(kind, **payload))

    async def close(self):
        await self.ws.close()

    def said(self):
        return [m["text"] for m in self.got if m["t"] == "say"]

    def last_state(self):
        states = [m for m in self.got if m["t"] == "state"]
        return states[-1] if states else {}


class ScriptedTranscriber:
    """Hears whatever the test says the next clip contains."""

    def __init__(self):
        self.next: list[str] = []

    def transcribe(self, pcm, rate):
        text = self.next.pop(0)
        return Transcript(text, 0.95 if text else 0.0, "[unk]" in text)


@pytest.fixture
def linked(tmp_path):
    bg = Loop()
    relay = FakeRelay()
    # CALLOUT_TEST_RELAY=http://127.0.0.1:8787 runs these against the real relay (npx wrangler dev in relay/).
    url = os.environ.get("CALLOUT_TEST_RELAY") or bg.run(relay.start())
    cfg = load_config(None)
    cfg.log_dir = str(tmp_path / "logs")
    cfg.safety.check_market_hours = False
    cfg.safety.min_seconds_between_orders = 0
    pairing = Pairing.new(url)
    conf = pairing.to_config()
    cfg.phone.relay, cfg.phone.room, cfg.phone.key = conf["relay"], conf["room"], conf["key"]
    s = Session(cfg, tmp_path / "config.toml", use_sim=True, audio=False, tts=False)
    s.start()
    assert wait_for(lambda: s.snapshot().get("connected"))
    assert wait_for(lambda: s.phone_view()["status"] == "waiting")
    s.phone_transcriber = ScriptedTranscriber()
    phone = FakePhone(pairing)
    bg.run(phone.connect())
    assert wait_for(lambda: s.phone_view()["status"] == "connected")
    yield s, phone, bg, relay
    s.stop()
    if relay.server:
        bg.run(relay.stop())
    bg.stop()


def test_button_commands_need_confirm_and_get_replies_and_state(linked):
    s, phone, bg, relay = linked
    assert wait_for(lambda: phone.last_state().get("connected"))
    bg.run(phone.send("cmd", text="buy es"))
    assert wait_for(lambda: any(t.startswith("Buy 1 ES") for t in phone.said()))  # "ES", not "E S", on screen
    assert wait_for(lambda: phone.last_state().get("pending"))
    bg.run(phone.send("cmd", text="confirm"))
    assert wait_for(lambda: any(t.startswith("Filled. Bought 1 ES") for t in phone.said()))
    assert wait_for(lambda: phone.last_state()["instruments"][0]["position"] == "long 1")
    assert all(b"Filled" not in f and b"buy" not in f for f in relay.frames)  # the relay saw only ciphertext
    assert relay.frames or os.environ.get("CALLOUT_TEST_RELAY")


def test_flatten_from_the_phone_always_asks_first(linked):
    s, phone, bg, _ = linked
    assert not s.cfg.safety.confirm_flatten  # flatten is instant at the PC...
    bg.run(phone.send("cmd", text="flatten"))
    assert wait_for(lambda: any("Say confirm" in t for t in phone.said()))  # ...but not from the phone
    assert s.snapshot().get("pending") or wait_for(lambda: s.snapshot().get("pending"))


def test_spoken_clips_need_the_wake_word(linked):
    s, phone, bg, _ = linked
    tr = s.phone_transcriber
    clip = pcm_to_b64(b"\x00\x01" * 8000)

    tr.next = ["buy e s"]  # someone on the court, no wake word
    bg.run(phone.send("clip", pcm=clip, rate=16000))
    time.sleep(0.5)
    assert phone.said() == [] and not s.snapshot().get("pending")

    tr.next = [f"{WAKE} buy e s"]
    bg.run(phone.send("clip", pcm=clip, rate=16000))
    assert wait_for(lambda: any(t.startswith("Buy 1 ES") for t in phone.said()))

    tr.next = ["confirm"]  # bare confirm counts while the readback waits
    bg.run(phone.send("clip", pcm=clip, rate=16000))
    assert wait_for(lambda: any(t.startswith("Filled.") for t in phone.said()))
    assert wait_for(lambda: s.snapshot()["instruments"][0]["qty"] == 1)

    tr.next = ["confirm"]  # nothing waiting now: ignored
    n = len(phone.said())
    bg.run(phone.send("clip", pcm=clip, rate=16000))
    time.sleep(0.5)
    assert len(phone.said()) == n


def test_frames_from_a_stranger_are_ignored(linked):
    s, phone, bg, _ = linked
    intruder = FakePhone(phone.pairing, key_override=b"\x07" * 32)
    bg.run(intruder.connect())  # takes the phone's place in the room...
    bg.run(intruder.send("cmd", text="buy es"))  # ...but can't seal frames with the real key
    assert wait_for(lambda: s.phone.bad_frames >= 1)
    time.sleep(0.3)
    assert not s.snapshot().get("pending")


def test_pairing_again_changes_the_key(linked):
    s, phone, bg, _ = linked
    old_key = s.cfg.phone.key
    r = s.pair_phone()
    assert r["ok"] and r["svg"].startswith("<svg") and "#" in r["link"]
    assert s.cfg.phone.key != old_key  # the old phone is cut off
    assert s.unpair_phone()["ok"] and not s.phone_view()["paired"]


def test_relay_address_must_be_https():
    from callout.config import ConfigError, validate

    cfg = load_config(None)
    cfg.phone.relay = "https://callout-relay.someone.workers.dev"
    validate(cfg)
    cfg.phone.relay = "http://callout-relay.someone.workers.dev"
    with pytest.raises(ConfigError, match="https"):
        validate(cfg)
