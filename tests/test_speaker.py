"""Spoken replies: Windows voice on its own thread, and falling back to text."""

import sys
import types

from callout.voice.speaker import Speaker


def test_windows_sapi_backend_used_and_called_on_worker_thread(monkeypatch):
    import threading

    spoken, inits = [], []

    class Voice:
        Rate = 0

        def Speak(self, text, flags):
            spoken.append((text, flags, threading.current_thread().name))

    client = types.ModuleType("comtypes.client")
    client.CreateObject = lambda name: Voice()
    comtypes = types.ModuleType("comtypes")
    comtypes.CoInitialize = lambda: inits.append(threading.current_thread().name)
    comtypes.client = client
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)
    monkeypatch.setattr(sys, "platform", "win32")

    sp = Speaker(enabled=True, echo=lambda s: None)
    assert sp.backend == "Windows SAPI"
    sp.say("one")
    sp.say("two")
    sp.close(wait=True)
    assert [t for t, _, _ in spoken] == ["one", "two"]
    assert inits and inits[0] == spoken[0][2]  # COM initialised on the same thread that speaks


def test_speech_failure_falls_back_to_text(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "pyttsx3", None)  # import fails

    lines = []
    sp = Speaker(enabled=True, echo=lines.append)
    assert sp.backend == "none" and sp.error
    sp.say("still printed")
    sp.close(wait=True)
    assert "  >> still printed" in lines
