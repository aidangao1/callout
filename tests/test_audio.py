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
