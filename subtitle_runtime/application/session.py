from __future__ import annotations

import inspect
import threading

from subtitle_runtime.application.ports import (
    AudioChunk,
    AudioSourcePort,
    SpeechPipelinePort,
    SpeechSegmenterPort,
    StatusSinkPort,
    SubtitleSinkPort,
)
from subtitle_runtime.domain.events import RuntimeState, RuntimeStatus


class SessionController:
    def __init__(
        self,
        *,
        audio_source: AudioSourcePort,
        speech_segmenter: SpeechSegmenterPort,
        speech_pipeline: SpeechPipelinePort,
        subtitle_sink: SubtitleSinkPort,
        status_sink: StatusSinkPort,
    ) -> None:
        self._audio_source = audio_source
        self._speech_segmenter = speech_segmenter
        self._speech_pipeline = speech_pipeline
        self._subtitle_sink = subtitle_sink
        self._status_sink = status_sink
        self._running = False
        self._stopped = False
        self._status_lock = threading.Lock()
        self.status = RuntimeStatus(state=RuntimeState.STARTING)

    def start(self) -> None:
        self._publish_status(RuntimeState.STARTING)
        self._stopped = False

        try:
            self._start_audio_source()
        except Exception as error:
            self._handle_error(error)
            return

        with self._status_lock:
            if self.status.state is RuntimeState.FAILED:
                return

        self._running = True
        self._publish_status(RuntimeState.RUNNING)

    def stop(self) -> None:
        if self._stopped:
            return

        try:
            self._audio_source.stop()
        finally:
            self._speech_segmenter.flush(self._handle_segment)
            self._running = False
            self._stopped = True

    def _handle_chunk(self, chunk: AudioChunk) -> None:
        self._speech_segmenter.process_chunk(chunk, self._handle_segment)

    def _handle_segment(self, segment: AudioChunk) -> None:
        event = self._speech_pipeline.process_segment(segment)

        if event is not None:
            self._subtitle_sink.publish(event)

    def _handle_error(self, error: Exception) -> None:
        del error
        self._running = False
        self._publish_status(RuntimeState.FAILED)

    def _start_audio_source(self) -> None:
        parameters = inspect.signature(self._audio_source.start).parameters

        if "on_error" in parameters:
            self._audio_source.start(self._handle_chunk, on_error=self._handle_error)
            return

        self._audio_source.start(self._handle_chunk)

    def _publish_status(self, state: RuntimeState) -> None:
        with self._status_lock:
            self.status = RuntimeStatus(state=state)
            self._status_sink.publish(self.status)
