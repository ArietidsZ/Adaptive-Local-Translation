from __future__ import annotations

import inspect
import queue
import signal
import sys
import threading
import time
from typing import Any

from subtitle_runtime.adapters.asr import ASRAdapter
from subtitle_runtime.adapters.audio_capture import AudioCaptureAdapter
from subtitle_runtime.adapters.obs_websocket import OBSWebSocketSubtitleAdapter
from subtitle_runtime.adapters.translator import TranslatorAdapter
from subtitle_runtime.adapters.vad import VADAdapter
from subtitle_runtime.application.audio_ingress import AudioIngress
from subtitle_runtime.application.session import SessionController
from subtitle_runtime.application.speech_pipeline import SpeechPipeline
from subtitle_runtime.domain.events import RuntimeState


class NullStatusSink:
    def publish(self, status: Any) -> None:
        del status


class _LazyAudioSource:
    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._adapter = None

    def start(self, on_chunk, *, on_error=None) -> None:
        adapter = self._get_adapter()
        start = getattr(adapter, "start")
        parameters = inspect.signature(start).parameters

        if "on_error" in parameters:
            start(on_chunk, on_error=on_error)
            return

        del on_error
        start(on_chunk)

    def stop(self) -> None:
        if self._adapter is None:
            return

        self._adapter.stop()

    def _get_adapter(self):
        if self._adapter is None:
            self._adapter = AudioCaptureAdapter(self._cfg)

        return self._adapter


class _LazySpeechSegmenter:
    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._adapter = None

    def process_chunk(self, chunk, on_speech) -> None:
        self._get_adapter().process_chunk(chunk, on_speech)

    def flush(self, on_speech) -> None:
        if self._adapter is None:
            return

        self._adapter.flush(on_speech)

    def _get_adapter(self):
        if self._adapter is None:
            self._adapter = VADAdapter(self._cfg)

        return self._adapter


class _LazySpeechPipeline:
    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._pipeline = None

    def process_segment(self, segment):
        return self._get_pipeline().process_segment(segment)

    def _get_pipeline(self):
        if self._pipeline is None:
            self._pipeline = SpeechPipeline(
                ASRAdapter(self._cfg),
                TranslatorAdapter(self._cfg),
                target_lang=self._cfg.translation_target_lang,
            )

        return self._pipeline


class _QueuedAudioSource:
    def __init__(self, audio_source: _LazyAudioSource, ingress: AudioIngress) -> None:
        self._audio_source = audio_source
        self._ingress = ingress
        self._drain_thread = None
        self._on_chunk = None
        self._stopping = False
        self._idle_wait = threading.Event()

    def start(self, on_chunk, *, on_error=None) -> None:
        self._on_chunk = on_chunk
        self._stopping = False
        self._drain_thread = threading.Thread(
            target=self._drain_loop,
            daemon=True,
            name="cli-audio-ingress",
        )
        self._drain_thread.start()

        try:
            self._audio_source.start(self._ingress.push, on_error=on_error)
        except Exception:
            self._stopping = True
            self._drain_thread.join(timeout=1.0)
            self._drain_thread = None
            raise

    def stop(self) -> None:
        self._audio_source.stop()
        self._stopping = True

        if self._drain_thread is not None:
            self._drain_thread.join(timeout=1.0)
            self._drain_thread = None

    def _drain_loop(self) -> None:
        while True:
            try:
                chunk = self._ingress.pop_nowait()
            except queue.Empty:
                if self._stopping:
                    return

                self._idle_wait.wait(0.01)
                continue

            if self._on_chunk is not None:
                self._on_chunk(chunk)


class _CLIRuntime:
    def __init__(self, cfg, *, subtitle_sink, status_sink) -> None:
        self._stop_event = threading.Event()
        self._ingress = AudioIngress(maxsize=200)
        self._capture_audio_source = _LazyAudioSource(cfg)
        self._audio_source = _QueuedAudioSource(
            self._capture_audio_source, self._ingress
        )
        self._speech_segmenter = _LazySpeechSegmenter(cfg)
        self._speech_pipeline = _LazySpeechPipeline(cfg)
        self._subtitle_sink = subtitle_sink
        self._status_sink = status_sink
        self.session = SessionController(
            audio_source=self._audio_source,
            speech_segmenter=self._speech_segmenter,
            speech_pipeline=self._speech_pipeline,
            subtitle_sink=subtitle_sink,
            status_sink=status_sink,
        )

    def run_forever(self) -> None:
        self._install_signal_handlers()

        try:
            while not self._stop_event.is_set():
                time.sleep(0.05)
        except KeyboardInterrupt:
            self._stop_event.set()

    def shutdown(self) -> None:
        self._stop_event.set()
        self.session.stop()
        self._subtitle_sink.clear()
        self._subtitle_sink.close()

    def close(self) -> None:
        self._subtitle_sink.close()

    def _publish_segment(self, segment) -> None:
        event = self._speech_pipeline.process_segment(segment)

        if event is not None:
            self._subtitle_sink.publish(event)

    def _install_signal_handlers(self) -> None:
        def _handler(sig, frame) -> None:
            del sig, frame
            self._stop_event.set()

        signal.signal(signal.SIGINT, _handler)
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, _handler)


def _build_cli_runtime(cfg, *, subtitle_sink, status_sink) -> _CLIRuntime:
    return _CLIRuntime(cfg, subtitle_sink=subtitle_sink, status_sink=status_sink)


def build_cli_session(cfg, *, subtitle_sink, status_sink) -> SessionController:
    return _build_cli_runtime(
        cfg,
        subtitle_sink=subtitle_sink,
        status_sink=status_sink,
    ).session


def run_cli(cfg) -> SessionController:
    runtime = _build_cli_runtime(
        cfg,
        subtitle_sink=OBSWebSocketSubtitleAdapter(cfg),
        status_sink=NullStatusSink(),
    )
    session = runtime.session
    session.start()

    if session.status.state is RuntimeState.FAILED:
        runtime.close()
        return session

    try:
        runtime.run_forever()
    finally:
        runtime.shutdown()

    return session
