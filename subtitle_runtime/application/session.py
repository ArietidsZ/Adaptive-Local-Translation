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
        self._lifecycle = "idle"
        self._status_lock = threading.RLock()
        self.status = RuntimeStatus(state=RuntimeState.STARTING)

    def start(self) -> None:
        with self._status_lock:
            self._running = False
            self._stopped = False
            self._lifecycle = "starting"
            self._publish_status_locked(RuntimeState.STARTING)

        try:
            self._start_audio_source()
        except Exception as error:
            self._handle_error(error)
            return

        with self._status_lock:
            if self._lifecycle != "starting":
                return

            self._running = True
            self._lifecycle = "running"
            self._publish_status_locked(RuntimeState.RUNNING)

    def stop(self) -> None:
        with self._status_lock:
            if self._stopped:
                return

            self._running = False
            self._stopped = True

            if self._lifecycle != "failed":
                self._lifecycle = "stopping"
                self._publish_status_locked(RuntimeState.STOPPING)

        try:
            self._audio_source.stop()
        finally:
            self._speech_segmenter.flush(self._handle_segment)

            with self._status_lock:
                if self._lifecycle != "failed":
                    self._lifecycle = "stopped"
                    self._publish_status_locked(RuntimeState.STOPPED)

    def _handle_chunk(self, chunk: AudioChunk) -> None:
        self._speech_segmenter.process_chunk(chunk, self._handle_segment)

    def _handle_segment(self, segment: AudioChunk) -> None:
        event = self._speech_pipeline.process_segment(segment)

        if event is not None:
            self._subtitle_sink.publish(event)

    def _handle_error(self, error: Exception) -> None:
        del error

        with self._status_lock:
            if self._stopped or self._lifecycle == "failed":
                return

            self._running = False
            self._lifecycle = "failed"
            self._publish_status_locked(RuntimeState.FAILED)

    def _start_audio_source(self) -> None:
        parameters = inspect.signature(self._audio_source.start).parameters

        if "on_error" in parameters:
            self._audio_source.start(self._handle_chunk, on_error=self._handle_error)
            return

        self._audio_source.start(self._handle_chunk)

    def _publish_status(self, state: RuntimeState) -> None:
        with self._status_lock:
            self._publish_status_locked(state)

    def _publish_status_locked(self, state: RuntimeState) -> None:
        self.status = RuntimeStatus(state=state)
        self._status_sink.publish(self.status)
