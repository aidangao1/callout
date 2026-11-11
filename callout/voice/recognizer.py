"""Offline speech-to-text with Vosk, locked to the app's phrase list.

Because the recognizer may only output known phrases (or "[unk]"), it can't
"creatively" hear an order that wasn't said. Per-word confidence is also
checked; anything shaky is rejected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Transcript:
    text: str
    confidence: float  # lowest per-word confidence, 0..1 (0 when nothing heard)
    has_unknown: bool

    @property
    def empty(self) -> bool:
        return not self.text.strip()


class Transcriber:
    def __init__(self, model: str, phrases: list[str], sample_rate: int = 16000):
        from vosk import KaldiRecognizer, Model, SetLogLevel  # lazy: heavy native lib

        SetLogLevel(-1)
        self._Recognizer = KaldiRecognizer
        self.sample_rate = sample_rate
        if Path(model).exists():
            self.model = Model(model_path=str(model))
        else:
            # A bare model name: vosk downloads it to ~/.cache/vosk on first use.
            self.model = Model(model_name=model)
        self.set_phrases(phrases)

    def set_phrases(self, phrases: list[str]) -> None:
        """Change what the recognizer may hear (after enabling an instrument or adding ignored words)."""
        keep, dropped = self._filter_phrases(phrases)
        if not keep:
            raise RuntimeError("None of the command phrases are in the speech model's vocabulary.")
        self.phrases, self.dropped = keep, dropped
        self._grammar = json.dumps(self.phrases + ["[unk]"])

    def _filter_phrases(self, phrases: list[str]) -> tuple[list[str], list[str]]:
        """Drop phrases containing words the model doesn't know (vosk would silently ignore them)."""
        find = getattr(self.model, "find_word", None) or getattr(self.model, "vosk_model_find_word", None)
        if find is None:
            return list(phrases), []
        keep, dropped = [], []
        for p in phrases:
            (keep if all(find(w) != -1 for w in p.split()) else dropped).append(p)
        return keep, dropped

    def transcribe(self, pcm16: bytes, sample_rate: int | None = None) -> Transcript:
        # Vosk resamples to the model's rate, so the mic's native rate is fine here.
        rec = self._Recognizer(self.model, sample_rate or self.sample_rate, self._grammar)
        rec.SetWords(True)
        rec.AcceptWaveform(pcm16)
        result = json.loads(rec.FinalResult())
        text = result.get("text", "").strip()
        words = result.get("result", [])
        has_unknown = "[unk]" in text
        conf = min((w.get("conf", 0.0) for w in words), default=0.0)
        return Transcript(text=text, confidence=conf, has_unknown=has_unknown)
