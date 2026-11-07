"""Push-to-talk logic with fake pynput and a fake recorder (no mic or display needed)."""

import enum
import sys
import threading
import time
import types

import pytest


@pytest.fixture
def fake_pynput(monkeypatch):
    class Key(enum.Enum):
        f9 = "f9"
        ctrl_r = "ctrl_r"

    class KeyCode:
        def __init__(self, char):
            self.char = char

        @classmethod
        def from_char(cls, c):
            return cls(c)

    kb = types.SimpleNamespace(Key=Key, KeyCode=KeyCode, Listener=None)
    mod = types.ModuleType("pynput")
    mod.keyboard = kb
    monkeypatch.setitem(sys.modules, "pynput", mod)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", kb)
    return kb


class FakeRecorder:
    def __init__(self):
        self.armed = 0
        self.disarmed = 0

    def arm(self):
        self.armed += 1

    def disarm(self):
        self.disarmed += 1
        return b"\x00\x00" * 16000


def make_ptt(fake_pynput, **kw):
    from callout.audio import PushToTalk

    got, states = [], []
    done = threading.Event()

    def on_utt(pcm, t):
        got.append((pcm, t))
        done.set()

    rec = FakeRecorder()
    ptt = PushToTalk(rec, "f9", on_utt, states.append, tail_s=0.01, **kw)
    return ptt, rec, got, states, done


def test_parse_key(fake_pynput):
    from callout.audio import key_matches, parse_key

    assert parse_key("F9") is fake_pynput.Key.f9
    k = parse_key("x")
    assert key_matches(fake_pynput.KeyCode("X"), k)
    assert not key_matches(fake_pynput.Key.ctrl_r, parse_key("f9"))
    with pytest.raises(ValueError):
        parse_key("hyperkey")


def test_hold_and_release_sends_once_despite_autorepeat(fake_pynput):
    ptt, rec, got, states, done = make_ptt(fake_pynput, min_duration_s=0.0)
    K = fake_pynput.Key
    ptt._press(K.f9)
    ptt._press(K.f9)  # OS auto-repeat while held
    ptt._press(K.f9)
    ptt._press(K.ctrl_r)  # other keys ignored
    ptt._release(K.f9)
    assert done.wait(1)
    assert rec.armed == 1 and rec.disarmed == 1 and len(got) == 1
    assert states == ["listening", "processing"]


def test_tap_too_short_is_ignored(fake_pynput):
    ptt, rec, got, states, done = make_ptt(fake_pynput, min_duration_s=5.0)
    ptt._press(fake_pynput.Key.f9)
    ptt._release(fake_pynput.Key.f9)
    time.sleep(0.1)
    assert got == [] and states[-1] == "too_short" and rec.disarmed == 1


def test_quick_repress_keeps_both_utterances(fake_pynput):
    from callout.audio import PushToTalk

    got = []
    rec = FakeRecorder()
    ptt = PushToTalk(rec, "f9", lambda pcm, t: got.append(t), lambda s: None, min_duration_s=0.0, tail_s=0.3)
    K = fake_pynput.Key
    ptt._press(K.f9)
    time.sleep(0.02)
    ptt._release(K.f9)  # tail timer now running
    ptt._press(K.f9)  # pressed again within the tail
    assert len(got) == 1  # first utterance closed out immediately
    time.sleep(0.02)
    ptt._release(K.f9)
    time.sleep(0.45)
    assert len(got) == 2 and rec.armed == 2 and rec.disarmed == 2


# ---- mic selection and level ------------------------------------------------------------------

from array import array  # noqa: E402


def pcm(*samples):
    return array("h", samples).tobytes()


def test_audio_level():
    from callout.audio import audio_level

    assert audio_level(b"") == 0.0
    assert audio_level(pcm(0, 0, 0)) == 0.0
    assert abs(audio_level(pcm(0, 16384, -100)) - 0.5) < 1e-6
    assert audio_level(pcm(-32768)) == 1.0


@pytest.fixture
def fake_sd(monkeypatch):
    devices = [
        {"name": "Speakers (Realtek)", "hostapi": 0, "max_input_channels": 0, "default_samplerate": 48000.0},
        {"name": "Microphone (Realtek)", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100.0},
        {"name": "Headset Mic (HyperX)", "hostapi": 1, "max_input_channels": 1, "default_samplerate": 48000.0},
        {"name": "Headset Mic (HyperX)", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 44100.0},
    ]
    opened = {}

    class Stream:
        def __init__(self, **kw):
            opened.update(kw)

    def check_input_settings(device=None, samplerate=None, **kw):
        if samplerate == 16000 and device == 2:
            raise RuntimeError("Invalid sample rate")

    def query_devices(device=None, kind=None):
        if device is None and kind is None:
            return devices
        return devices[1 if device is None else device]

    mod = types.ModuleType("sounddevice")
    mod.default = types.SimpleNamespace(device=(1, 0), hostapi=0)
    mod.query_devices = query_devices
    mod.query_hostapis = lambda i: {"name": ["MME", "Windows WASAPI"][i]}
    mod.check_input_settings = check_input_settings
    mod.RawInputStream = Stream
    monkeypatch.setitem(sys.modules, "sounddevice", mod)
    return opened


def test_list_and_resolve_devices(fake_sd):
    from callout.audio import list_input_devices, resolve_input_device

    devs = list_input_devices()
    assert [d["index"] for d in devs] == [1, 2, 3] and devs[0]["default"]
    assert resolve_input_device("") is None
    assert resolve_input_device("2") == 2
    assert resolve_input_device("hyperx") == 3  # prefers the default audio system (MME)
    with pytest.raises(ValueError):
        resolve_input_device("0")  # speakers, not a mic
    with pytest.raises(ValueError):
        resolve_input_device("blue yeti")


def test_recorder_falls_back_to_native_rate(fake_sd):
    from callout.audio import Recorder

    r = Recorder(16000, device=2)
    assert r.sample_rate == 48000 and fake_sd["samplerate"] == 48000 and fake_sd["device"] == 2
    r = Recorder(0)  # 0 = native rate of the default mic
    assert r.sample_rate == 44100 and r.device_name == "Microphone (Realtek)"
