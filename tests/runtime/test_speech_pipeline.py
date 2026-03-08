from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from subtitle_runtime.application.speech_pipeline import SpeechPipeline


class FakeTranscriber:
    def transcribe(self, segment):
        return type("Result", (), {"text": "hello", "language": "English"})()


class FakeTranslator:
    def translate(self, text, source_lang=None, target_lang=None):
        assert text == "hello"
        assert source_lang == "English"
        assert target_lang == "zh"
        return "你好"


def test_speech_pipeline_returns_subtitle_event() -> None:
    pipeline = SpeechPipeline(FakeTranscriber(), FakeTranslator(), target_lang="zh")

    event = pipeline.process_segment(np.array([0.25], dtype=np.float32))

    assert event is not None
    assert event.translated_text == "你好"
    assert event.source_language == "English"
    assert event.latency_ms >= 0
