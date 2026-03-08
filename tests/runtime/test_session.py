from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from subtitle_runtime.application.session import SessionController
from subtitle_runtime.domain.events import RuntimeState


class FakeAudioSource:
    def start(self, on_chunk, *, on_error=None):
        self.on_chunk = on_chunk

    def stop(self):
        self.stopped = True


class FakeSegmenter:
    def process_chunk(self, chunk, on_speech):
        on_speech(chunk)

    def flush(self, on_speech):
        return None


class FakeSubtitleSink:
    def __init__(self):
        self.values = []

    def publish(self, event):
        self.values.append(event)


class FakeStatusSink:
    def __init__(self):
        self.values = []

    def publish(self, status):
        self.values.append(status)


def test_session_transitions_to_running() -> None:
    session = SessionController(
        audio_source=FakeAudioSource(),
        speech_segmenter=FakeSegmenter(),
        speech_pipeline=type(
            "Pipeline", (), {"process_segment": lambda self, segment: None}
        )(),
        subtitle_sink=FakeSubtitleSink(),
        status_sink=FakeStatusSink(),
    )

    session.start()

    assert session.status.state == RuntimeState.RUNNING
