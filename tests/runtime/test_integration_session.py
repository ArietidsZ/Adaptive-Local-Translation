from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from subtitle_runtime.application.session import SessionController
from subtitle_runtime.application.speech_pipeline import SpeechPipeline


class FakeAudioSource:
    def start(self, on_chunk, *, on_error=None):
        on_chunk(np.array([0.25], dtype=np.float32))

    def stop(self):
        return None


class FakeSegmenter:
    def process_chunk(self, chunk, on_speech):
        on_speech(chunk)

    def flush(self, on_speech):
        return None


class FakeTranscriber:
    def transcribe(self, segment):
        return type("Result", (), {"text": "hello", "language": "English"})()


class FakeTranslator:
    def translate(self, text, source_lang=None, target_lang=None):
        return "你好"


class CollectingSink:
    def __init__(self):
        self.values = []

    def publish(self, value):
        self.values.append(value)


def test_session_emits_translated_subtitle_from_fake_runtime() -> None:
    subtitle_sink = CollectingSink()
    status_sink = CollectingSink()
    session = SessionController(
        audio_source=FakeAudioSource(),
        speech_segmenter=FakeSegmenter(),
        speech_pipeline=SpeechPipeline(
            FakeTranscriber(),
            FakeTranslator(),
            target_lang="zh",
        ),
        subtitle_sink=subtitle_sink,
        status_sink=status_sink,
    )

    session.start()

    assert subtitle_sink.values[-1].translated_text == "你好"
    assert status_sink.values[0].state.value == "starting"
    assert status_sink.values[-1].state.value == "running"
