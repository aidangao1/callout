"""Spoken readback. Runs on its own thread so speaking never blocks trading."""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading
from typing import Callable

# SAPI SpVoice.Speak flags
SVSF_PURGE_BEFORE_SPEAK = 2


class Speaker:
    def __init__(self, enabled: bool = True, echo=print):
        self.enabled = enabled
        self.echo = echo
        self.backend = "off"
        self.error = ""
        self._q: queue.Queue[str | None] = queue.Queue()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        if enabled:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._ready.wait(10)  # so callers can report which voice loaded (or why none did)
        else:
            self._ready.set()

    def say(self, text: str, interrupt: bool = False) -> None:
        self.echo(f"  >> {text}")
        if not self.enabled:
            return
        if interrupt:  # drop anything still queued; the newest message matters most
            try:
                while True:
                    self._q.get_nowait()
            except queue.Empty:
                pass
        self._q.put(text)

    def close(self, wait: bool = False) -> None:
        if self._thread:
            self._q.put(None)
            if wait:
                self._thread.join(timeout=15)

    def _run(self) -> None:
        try:
            speak = self._backend()
        except Exception as e:
            self.backend, self.error = "none", str(e)
            speak = None
        self._ready.set()
        if speak is None:
            self.echo(f"  (no speech output: {self.error}; text only)")
        while True:
            text = self._q.get()
            if text is None:
                return
            if speak is None:
                continue
            try:
                speak(text)
            except Exception as e:  # never let audio problems take the app down
                self.error = str(e)
                self.echo(f"  (speech output failed: {e}; continuing with text only)")
                speak = None

    def _backend(self) -> Callable[[str], None]:
        if sys.platform == "darwin" and shutil.which("say"):
            self.backend = "macOS say"
            return lambda t: subprocess.run(["say", "-r", "220", t], check=False)
        if sys.platform == "win32":
            try:
                return self._windows_sapi()
            except Exception as e:
                self.error = f"Windows voice: {e}"
        return self._pyttsx3()

    def _windows_sapi(self) -> Callable[[str], None]:
        """Windows' built-in voice, called directly. More reliable than pyttsx3 off the main thread."""
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()  # COM must be initialised on the thread that uses it
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
        voice.Rate = 2  # -10 (slow) .. 10 (fast)
        self.backend = "Windows SAPI"
        return lambda t: voice.Speak(t, SVSF_PURGE_BEFORE_SPEAK)

    def _pyttsx3(self) -> Callable[[str], None]:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 210)
        self.backend = "pyttsx3"

        def speak(t: str) -> None:
            engine.say(t)
            engine.runAndWait()

        return speak


class SilentSpeaker(Speaker):
    """Records what would have been said. Used by tests."""

    def __init__(self):
        super().__init__(enabled=False, echo=lambda s: None)
        self.said: list[str] = []

    def say(self, text: str, interrupt: bool = False) -> None:
        self.said.append(text)
