"""Spoken readback. Runs on its own thread so speaking never blocks trading."""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading


class Speaker:
    def __init__(self, enabled: bool = True, echo=print):
        self.enabled = enabled
        self.echo = echo
        self._q: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        if enabled:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

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

    def close(self) -> None:
        if self._thread:
            self._q.put(None)

    def _run(self) -> None:
        speak = self._backend()
        while True:
            text = self._q.get()
            if text is None:
                return
            try:
                speak(text)
            except Exception as e:  # never let audio problems take the app down
                self.echo(f"  (speech output failed: {e}; continuing with text only)")
                speak = lambda t: None  # noqa: E731

    def _backend(self):
        if sys.platform == "darwin" and shutil.which("say"):
            return lambda t: subprocess.run(["say", "-r", "220", t], check=False)
        try:
            if sys.platform == "win32":
                try:
                    import comtypes  # pyttsx3's SAPI driver needs COM initialised on this thread

                    comtypes.CoInitialize()
                except Exception:
                    pass
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 210)

            def speak(t: str) -> None:
                engine.say(t)
                engine.runAndWait()

            return speak
        except Exception as e:
            self.echo(f"  (no speech output available: {e}; text only)")
            return lambda t: None


class SilentSpeaker(Speaker):
    """Records what would have been said. Used by tests."""

    def __init__(self):
        super().__init__(enabled=False, echo=lambda s: None)
        self.said: list[str] = []

    def say(self, text: str, interrupt: bool = False) -> None:
        self.said.append(text)
