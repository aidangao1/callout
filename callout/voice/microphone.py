"""Microphone: finding mics, measuring level, and recording.

The mic stream stays open, but audio is only kept while the talk key is held
(plus a short pre-roll so the first syllable isn't clipped). Nothing is
recorded or sent anywhere otherwise.
"""

from __future__ import annotations

import threading
import time
from collections import deque


def audio_level(pcm16: bytes) -> float:
    """Peak level of 16-bit PCM audio, 0.0 (silence) to 1.0 (full scale)."""
    from array import array

    samples = array("h")
    samples.frombytes(pcm16[: len(pcm16) - len(pcm16) % 2])
    if not samples:
        return 0.0
    return min(1.0, max(abs(min(samples)), max(samples)) / 32768)


def list_input_devices() -> list[dict]:
    import sounddevice as sd

    default_in = sd.default.device[0] if sd.default.device else None
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append(
                {
                    "index": i,
                    "name": d["name"],
                    "hostapi": sd.query_hostapis(d["hostapi"])["name"],
                    "rate": int(d["default_samplerate"]),
                    "default": i == default_in,
                }
            )
    return out


def main_input_devices() -> list[dict]:
    """One entry per mic: just the default audio system's list (MME on Windows)."""
    import sounddevice as sd

    try:
        api = sd.query_hostapis(sd.default.hostapi)["name"]
    except Exception:
        return list_input_devices()
    return [d for d in list_input_devices() if d["hostapi"] == api]


def resolve_input_device(spec: str | int | None):
    """'' -> system default; '3' -> device 3; 'yeti' -> first input device whose name contains it."""
    if spec is None or str(spec).strip() == "":
        return None
    spec = str(spec).strip()
    devices = list_input_devices()
    if spec.isdigit():
        idx = int(spec)
        if not any(d["index"] == idx for d in devices):
            raise ValueError(f"Input device {idx} doesn't exist or isn't a microphone. Run: python -m callout devices")
        return idx
    import sounddevice as sd

    default_api = sd.query_hostapis(sd.default.hostapi)["name"] if sd.default.hostapi is not None else None
    matches = [d for d in devices if spec.lower() in d["name"].lower()]
    matches.sort(key=lambda d: d["hostapi"] != default_api)  # prefer the default audio system's entry
    if not matches:
        raise ValueError(f"No microphone matching '{spec}'. Run: python -m callout devices")
    return matches[0]["index"]


def _extra_settings(sd, device):
    """WASAPI won't open a mic in mono at a non-native format unless asked to convert."""
    try:
        info = sd.query_devices(device, "input")
        if "WASAPI" in sd.query_hostapis(info["hostapi"])["name"]:
            return sd.WasapiSettings(auto_convert=True)
    except Exception:
        pass
    return None


def sample_device(device: int, rate: int, seconds: float = 1.5) -> tuple[bytes, int]:
    """Record a short clip from one device. Returns (pcm16 mono, number of audio blocks received)."""
    import sounddevice as sd

    chunks: list[bytes] = []
    with sd.RawInputStream(
        samplerate=rate,
        channels=1,
        dtype="int16",
        device=device,
        extra_settings=_extra_settings(sd, device),
        callback=lambda indata, n, t, st: chunks.append(bytes(indata)),
    ):
        time.sleep(seconds)
    return b"".join(chunks), len(chunks)


class Recorder:
    def __init__(self, sample_rate: int = 0, device=None, preroll_s: float = 0.3, block_s: float = 0.05):
        import sounddevice as sd  # lazy: needs PortAudio

        info = sd.query_devices(device, "input")
        self.device_name = info["name"]
        rates = [sample_rate] if sample_rate else []
        rates.append(int(info["default_samplerate"]))  # the mic's native rate always works
        last_error = None
        for rate in rates:
            try:
                sd.check_input_settings(
                    device=device,
                    samplerate=rate,
                    channels=1,
                    dtype="int16",
                    extra_settings=_extra_settings(sd, device),
                )
            except Exception as e:
                last_error = e
                continue
            self.sample_rate = rate
            break
        else:
            raise RuntimeError(f"Microphone '{self.device_name}' can't be opened: {last_error}")

        blocksize = int(self.sample_rate * block_s)
        self._pre: deque[bytes] = deque(maxlen=max(1, int(preroll_s / block_s)))
        self._buf: list[bytes] = []
        self._armed = False
        self._lock = threading.Lock()
        self.callbacks = 0  # how many audio blocks have arrived; 0 after a second means a dead stream
        self.level = 0.0  # live peak level 0..1 with a short decay, for the on-screen meter
        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=blocksize,
            channels=1,
            dtype="int16",
            device=device,
            extra_settings=_extra_settings(sd, device),
            callback=self._callback,
        )

    def _callback(self, indata, frames, t, status) -> None:
        chunk = bytes(indata)
        peak = audio_level(chunk)
        with self._lock:
            self.callbacks += 1
            self.level = max(peak, self.level * 0.8)
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
