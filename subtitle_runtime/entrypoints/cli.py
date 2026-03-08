from __future__ import annotations

import time
from typing import Any

from subtitle_runtime.adapters.asr import ASRAdapter
from subtitle_runtime.adapters.audio_capture import AudioCaptureAdapter
from subtitle_runtime.adapters.obs_websocket import OBSWebSocketSubtitleAdapter
from subtitle_runtime.adapters.translator import TranslatorAdapter
from subtitle_runtime.adapters.vad import VADAdapter
from subtitle_runtime.application.session import SessionController
from subtitle_runtime.application.speech_pipeline import SpeechPipeline


class NullStatusSink:
    def publish(self, status: Any) -> None:
        del status


class _LazyAudioSource:
    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._adapter = None

    def start(self, on_chunk, *, on_error=None) -> None:
        del on_error
        self._get_adapter().start(on_chunk)

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


def build_cli_session(cfg, *, subtitle_sink, status_sink) -> SessionController:
    return SessionController(
        audio_source=_LazyAudioSource(cfg),
        speech_segmenter=_LazySpeechSegmenter(cfg),
        speech_pipeline=_LazySpeechPipeline(cfg),
        subtitle_sink=subtitle_sink,
        status_sink=status_sink,
    )


def run_cli(cfg) -> SessionController:
    subtitle_sink = OBSWebSocketSubtitleAdapter(cfg)
    session = build_cli_session(
        cfg,
        subtitle_sink=subtitle_sink,
        status_sink=NullStatusSink(),
    )
    session.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        session._audio_source.stop()
        session._speech_segmenter.flush(session._handle_segment)
        subtitle_sink.clear()
        subtitle_sink.close()

    return session
