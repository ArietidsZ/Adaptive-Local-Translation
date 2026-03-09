from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import numpy as np


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from subtitle_runtime.application.ports import AudioSourcePort
from subtitle_runtime.application.session import SessionController
from subtitle_runtime.domain.events import RuntimeState, SubtitleEvent


class FakeAudioSource:
    def __init__(self, *, startup_error: Exception | None = None):
        self._startup_error = startup_error
        self.stopped = False

    def start(self, on_chunk, *, on_error=None):
        if self._startup_error is not None:
            raise self._startup_error

        self.on_chunk = on_chunk
        self.on_error = on_error

    def stop(self):
        self.stopped = True


class LegacyAudioSource:
    def start(self, on_chunk):
        self.on_chunk = on_chunk

    def stop(self):
        self.stopped = True


class FakeSegmenter:
    def __init__(self) -> None:
        self.flushed = False

    def process_chunk(self, chunk, on_speech):
        on_speech(chunk)

    def flush(self, on_speech):
        self.flushed = True
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


class FakePipeline:
    def __init__(self, event: SubtitleEvent | None = None):
        self._event = event

    def process_segment(self, segment):
        return self._event


def build_session(
    *,
    audio_source: object | None = None,
    speech_segmenter: FakeSegmenter | None = None,
    speech_pipeline: FakePipeline | None = None,
):
    subtitle_sink = FakeSubtitleSink()
    status_sink = FakeStatusSink()
    segmenter = speech_segmenter or FakeSegmenter()
    session = SessionController(
        audio_source=cast(AudioSourcePort, audio_source or FakeAudioSource()),
        speech_segmenter=segmenter,
        speech_pipeline=speech_pipeline or FakePipeline(),
        subtitle_sink=subtitle_sink,
        status_sink=status_sink,
    )

    return session, subtitle_sink, status_sink, segmenter


def test_session_publishes_starting_then_running_statuses() -> None:
    session, _, status_sink, _ = build_session()

    session.start()

    assert [status.state for status in status_sink.values] == [
        RuntimeState.STARTING,
        RuntimeState.RUNNING,
    ]


def test_session_publishes_failed_status_when_startup_raises() -> None:
    session, _, status_sink, _ = build_session(
        audio_source=FakeAudioSource(startup_error=RuntimeError("boom"))
    )

    session.start()

    assert [status.state for status in status_sink.values] == [
        RuntimeState.STARTING,
        RuntimeState.FAILED,
    ]


def test_session_does_not_publish_running_after_startup_async_failure() -> None:
    class FailingDuringStartAudioSource:
        def start(self, on_chunk, *, on_error=None):
            del on_chunk
            on_error(RuntimeError("boom"))

        def stop(self):
            return None

    session, _, status_sink, _ = build_session(
        audio_source=FailingDuringStartAudioSource()
    )

    session.start()

    assert session.status.state is RuntimeState.FAILED
    assert [status.state for status in status_sink.values] == [
        RuntimeState.STARTING,
        RuntimeState.FAILED,
    ]


def test_session_publishes_pipeline_output_to_subtitle_sink() -> None:
    event = SubtitleEvent(
        source_text="hello",
        source_language="en",
        translated_text="ni hao",
        latency_ms=1.0,
    )
    session, subtitle_sink, _, _ = build_session(
        speech_pipeline=FakePipeline(event=event)
    )

    session.start()
    session._handle_chunk(np.array([0.5], dtype=np.float32))

    assert subtitle_sink.values == [event]


def test_session_supports_legacy_audio_source_start_signature() -> None:
    session, _, status_sink, _ = build_session(audio_source=LegacyAudioSource())

    session.start()

    assert [status.state for status in status_sink.values] == [
        RuntimeState.STARTING,
        RuntimeState.RUNNING,
    ]


def test_session_stop_stops_audio_source_and_flushes_segmenter() -> None:
    audio_source = FakeAudioSource()
    segmenter = FakeSegmenter()
    session, _, status_sink, _ = build_session(
        audio_source=audio_source,
        speech_segmenter=segmenter,
    )

    session.start()
    session.stop()

    assert audio_source.stopped is True
    assert segmenter.flushed is True
    assert [status.state for status in status_sink.values] == [
        RuntimeState.STARTING,
        RuntimeState.RUNNING,
        RuntimeState.STOPPING,
        RuntimeState.STOPPED,
    ]


def test_session_stop_cleans_up_after_async_error() -> None:
    audio_source = FakeAudioSource()
    segmenter = FakeSegmenter()
    session, _, status_sink, _ = build_session(
        audio_source=audio_source,
        speech_segmenter=segmenter,
    )

    session.start()
    audio_source.on_error(RuntimeError("boom"))
    session.stop()

    assert audio_source.stopped is True
    assert segmenter.flushed is True
    assert status_sink.values[-1].state is RuntimeState.FAILED


def test_session_stop_preserves_failed_status_after_async_error() -> None:
    audio_source = FakeAudioSource()
    session, _, status_sink, _ = build_session(audio_source=audio_source)

    session.start()
    audio_source.on_error(RuntimeError("boom"))
    session.stop()

    assert [status.state for status in status_sink.values] == [
        RuntimeState.STARTING,
        RuntimeState.RUNNING,
        RuntimeState.FAILED,
    ]


def test_session_ignores_late_async_error_after_stop() -> None:
    audio_source = FakeAudioSource()
    session, _, status_sink, _ = build_session(audio_source=audio_source)

    session.start()
    session.stop()
    audio_source.on_error(RuntimeError("boom"))

    assert [status.state for status in status_sink.values] == [
        RuntimeState.STARTING,
        RuntimeState.RUNNING,
        RuntimeState.STOPPING,
        RuntimeState.STOPPED,
    ]
