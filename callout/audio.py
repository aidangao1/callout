"""Microphone capture and push-to-talk.

The mic stream stays open, but audio is only kept while the talk key is held
(plus a short pre-roll so the first syllable isn't clipped). Nothing is
recorded or sent anywhere otherwise.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

UtteranceHandler = Callable[[bytes, float], None]  # (pcm16 audio, monotonic time key was released)
StateHandler = Callable[[str], None]  # "listening" / "processing"


class Recorder:
    def __init__(self, sample_rate: int = 16000, preroll_s: float = 0.3, block_s: float = 0.05):
        import sounddevice as sd  # lazy: needs PortAudio

        self.sample_rate = sample_rate
        blocksize = int(sample_rate * block_s)
        self._pre: deque[bytes] = deque(maxlen=max(1, int(preroll_s / block_s)))
        self._buf: list[bytes] = []
        self._armed = False
        self._lock = threading.Lock()
        self._stream = sd.RawInputStream(
            samplerate=sample_rate, blocksize=blocksize, channels=1, dtype="int16", callback=self._callback
        )

    def _callback(self, indata, frames, t, status) -> None:
        chunk = bytes(indata)
        with self._lock:
            (self._buf if self._armed else self._pre).append(chunk)

    def start(self) -> None:
        self._stream.start()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()

    def arm(self) -> None:
        with self._lock:
            self._buf = list(self._pre)
            self._armed = True

    def disarm(self) -> bytes:
        with self._lock:
            self._armed = False
            data, self._buf = b"".join(self._buf), []
            self._pre.clear()  # don't prepend audio from before this utterance to the next one
        return data

    def seconds(self, pcm: bytes) -> float:
        return len(pcm) / 2 / self.sample_rate


def parse_key(name: str):
    from pynput import keyboard

    name = name.strip().lower()
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    valid = ", ".join(k.name for k in keyboard.Key)
    raise ValueError(f"Unknown push-to-talk key '{name}'. Use a single character or one of: {valid}")


def key_matches(key, target) -> bool:
    if key == target:
        return True
    kc, tc = getattr(key, "char", None), getattr(target, "char", None)
    return kc is not None and tc is not None and kc.lower() == tc.lower()


class PushToTalk:
    """Hold a global hotkey to talk; release to send. Works while TWS has focus."""

    def __init__(
        self,
        recorder: Recorder,
        key_name: str,
        on_utterance: UtteranceHandler,
        on_state: StateHandler = lambda s: None,
        min_duration_s: float = 0.25,
        tail_s: float = 0.15,
    ):
        self.recorder = recorder
        self.key = parse_key(key_name)
        self.on_utterance = on_utterance
        self.on_state = on_state
        self.min_duration_s = min_duration_s
        self.tail_s = tail_s
        self._down = False
        self._t_press = 0.0
        self._listener = None
        self._lock = threading.Lock()
        self._seq = 0
        self._pending: tuple[int, float, float] | None = None  # (seq, t_press, t_release) awaiting its tail
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        from pynput import keyboard

        self.recorder.start()
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
        if self._timer:
            self._timer.cancel()
        self.recorder.close()

    def _press(self, key) -> None:
        if not key_matches(key, self.key) or self._down:  # ignore other keys and OS auto-repeat
            return
        with self._lock:
            # Pressed again before the previous utterance's tail finished: close that one out
            # first so the two never bleed into each other.
            if self._timer:
                self._timer.cancel()
                self._timer = None
            previous = self._take_pending()
            self._down = True
            self._t_press = time.monotonic()
            self.recorder.arm()
        if previous:
            self._emit(*previous)
        self.on_state("listening")

    def _release(self, key) -> None:
        if not key_matches(key, self.key) or not self._down:
            return
        with self._lock:
            self._down = False
            self._seq += 1
            self._pending = (self._seq, self._t_press, time.monotonic())
            self._timer = threading.Timer(self.tail_s, self._finish, args=(self._seq,))
            self._timer.start()

    def _finish(self, seq: int) -> None:
        with self._lock:
            if self._pending is None or self._pending[0] != seq:
                return  # already closed out by a new press
            self._timer = None
            done = self._take_pending()
        if done:
            self._emit(*done)

    def _take_pending(self):
        """Call with the lock held. Stops recording and returns (pcm, t_press, t_release)."""
        if self._pending is None:
            return None
        _, t_press, t_release = self._pending
        self._pending = None
        return self.recorder.disarm(), t_press, t_release

    def _emit(self, pcm: bytes, t_press: float, t_release: float) -> None:
        if t_release - t_press < self.min_duration_s:
            self.on_state("too_short")
            return
        self.on_state("processing")
        self.on_utterance(pcm, t_release)


class EnterToTalk:
    """Fallback when global hotkeys aren't available: Enter to start, Enter to stop."""

    def __init__(self, recorder: Recorder, on_utterance: UtteranceHandler, on_state: StateHandler = lambda s: None):
        self.recorder = recorder
        self.on_utterance = on_utterance
        self.on_state = on_state
        self._stop = threading.Event()

    def start(self) -> None:
        self.recorder.start()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.recorder.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                input()
            except EOFError:
                return
            self.recorder.arm()
            self.on_state("listening_enter")
            try:
                input()
            except EOFError:
                return
            t_release = time.monotonic()
            time.sleep(0.15)
            pcm = self.recorder.disarm()
            self.on_state("processing")
            self.on_utterance(pcm, t_release)
