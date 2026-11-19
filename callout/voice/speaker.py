"""Spoken readback. Runs on its own thread so speaking never blocks trading."""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable

# SAPI SpVoice.Speak flags
SVSF_PURGE_BEFORE_SPEAK = 2


class Speaker:
    def __init__(self, enabled: bool = True, echo=print, rate: int = 2, volume: int = 100):
        self.enabled = enabled
        self.echo = echo
        self.rate = rate  # -10 (slow) .. 10 (fast)
        self.volume = volume  # 0 .. 100
        self.backend = "off"
        self.error = ""
        self._q: queue.Queue[str | None] = queue.Queue()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        if enabled:
            self._start_thread()
        else:
            self._ready.set()

    def _start_thread(self) -> None:
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(10)  # so callers can report which voice loaded (or why none did)

    def set_enabled(self, enabled: bool) -> None:
        """Turn spoken replies on or off while running."""
        self.enabled = enabled
        if enabled and (self._thread is None or not self._thread.is_alive()):
            self._start_thread()

    def set_voice(self, rate: int | None = None, volume: int | None = None) -> None:
        if rate is not None:
            self.rate = max(-10, min(10, int(rate)))
        if volume is not None:
            self.volume = max(0, min(100, int(volume)))

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
            return lambda t: subprocess.run(["say", "-r", str(200 + self.rate * 12), t], check=False)
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
        self.backend = "Windows SAPI"

        def speak(t: str) -> None:
            voice.Rate = self.rate
            voice.Volume = self.volume
            voice.Speak(t, SVSF_PURGE_BEFORE_SPEAK)

        return speak

    def _pyttsx3(self) -> Callable[[str], None]:
        import pyttsx3

        engine = pyttsx3.init()
        self.backend = "pyttsx3"

        def speak(t: str) -> None:
            engine.setProperty("rate", 200 + self.rate * 12)
            engine.setProperty("volume", self.volume / 100)
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


# ---- replies as audio, for the phone --------------------------------------------------------------

SAFT16K_16BIT_MONO = 18  # SAPI audio format: 16 kHz, 16-bit, mono (small enough to send quickly)
SSFM_CREATE_FOR_WRITE = 3


def render_wav(text: str, rate: int = 2, volume: int = 100) -> bytes | None:
    """Speak `text` into a WAV file instead of the speakers, and return its bytes.

    Used to send replies to the phone so they play in the earbuds. Returns None if no
    voice is available; the phone then speaks the text with its own voice.
    """
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        if sys.platform == "win32":
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            try:
                fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
                fmt.Type = SAFT16K_16BIT_MONO
                stream = comtypes.client.CreateObject("SAPI.SpFileStream")
                stream.Format = fmt
                stream.Open(path, SSFM_CREATE_FOR_WRITE)
                voice = comtypes.client.CreateObject("SAPI.SpVoice")
                voice.AudioOutputStream = stream
                voice.Rate, voice.Volume = rate, volume
                voice.Speak(text)
                stream.Close()
            finally:
                comtypes.CoUninitialize()
        else:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 200 + rate * 12)
            engine.setProperty("volume", volume / 100)
            engine.save_to_file(text, path)
            engine.runAndWait()
        with open(path, "rb") as f:
            data = f.read()
        return data if len(data) > 44 else None  # a bare header means nothing was spoken
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
