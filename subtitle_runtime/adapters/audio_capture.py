from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from subtitle_runtime.application.ports import AudioChunk

from audio import AudioCapture


class AudioCaptureFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


class AudioCaptureAdapter:
    def __init__(self, cfg: Any, factory: AudioCaptureFactory = AudioCapture) -> None:
        self._audio_capture = factory(cfg)

    def start(self, on_chunk: Callable[[AudioChunk], None]) -> None:
        self._audio_capture.start(on_chunk)

    def stop(self) -> None:
        self._audio_capture.stop()
