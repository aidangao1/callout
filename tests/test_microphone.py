"""Mic level, picking a mic, and opening it at a rate it supports (fake sounddevice)."""

import sys
import types
from array import array

import pytest


def pcm(*samples):
    return array("h", samples).tobytes()


def test_audio_level():
    from callout.voice.microphone import audio_level

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
    from callout.voice.microphone import list_input_devices, resolve_input_device

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
    from callout.voice.microphone import Recorder

    r = Recorder(16000, device=2)
    assert r.sample_rate == 48000 and fake_sd["samplerate"] == 48000 and fake_sd["device"] == 2
    r = Recorder(0)  # 0 = native rate of the default mic
    assert r.sample_rate == 44100 and r.device_name == "Microphone (Realtek)"
