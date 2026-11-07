"""Transcriber with a fake vosk module: grammar building, vocab filtering, confidence."""

import json
import sys
import types


def install_fake_vosk(monkeypatch, vocab, result):
    captured = {}

    class Model:
        def __init__(self, model_path=None, model_name=None, lang=None):
            captured["model"] = model_path or model_name

        def vosk_model_find_word(self, w):
            return 1 if w in vocab else -1

    class KaldiRecognizer:
        def __init__(self, model, rate, grammar):
            captured["grammar"] = json.loads(grammar)
            captured["rate"] = rate

        def SetWords(self, on):
            captured["words"] = on

        def AcceptWaveform(self, data):
            return True

        def FinalResult(self):
            return json.dumps(result)

    mod = types.ModuleType("vosk")
    mod.Model, mod.KaldiRecognizer, mod.SetLogLevel = Model, KaldiRecognizer, lambda n: None
    monkeypatch.setitem(sys.modules, "vosk", mod)
    return captured


def test_vocab_filter_and_confidence(monkeypatch):
    from callout.stt import Transcriber

    result = {"text": "buy e s", "result": [{"word": "buy", "conf": 0.98}, {"word": "e", "conf": 0.81},
                                           {"word": "s", "conf": 0.93}]}
    cap = install_fake_vosk(monkeypatch, {"buy", "sell", "e", "s", "confirm"}, result)
    t = Transcriber("vosk-model-small-en-us-0.15", ["buy e s", "sell e s", "buy es", "confirm"])
    assert t.dropped == ["buy es"]  # "es" not in the model's vocabulary
    tr = t.transcribe(b"\x00" * 3200)
    assert cap["grammar"] == ["buy e s", "sell e s", "confirm", "[unk]"]
    assert cap["words"] is True
    assert tr.text == "buy e s" and abs(tr.confidence - 0.81) < 1e-9 and not tr.has_unknown


def test_unknown_and_silence(monkeypatch):
    from callout.stt import Transcriber

    install_fake_vosk(monkeypatch, {"buy", "e", "s"}, {"text": "[unk] e s", "result": [{"word": "[unk]", "conf": 1.0}]})
    tr = Transcriber("m", ["buy e s"]).transcribe(b"")
    assert tr.has_unknown

    install_fake_vosk(monkeypatch, {"buy", "e", "s"}, {"text": ""})
    tr = Transcriber("m", ["buy e s"]).transcribe(b"")
    assert tr.empty and tr.confidence == 0.0
