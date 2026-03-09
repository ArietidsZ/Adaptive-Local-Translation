from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Protocol

from subtitle_runtime.application.ports import AudioChunk


class AudioCaptureFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


def _default_factory(cfg: Any) -> Any:
    from audio import AudioCapture

    return AudioCapture(cfg)


class AudioCaptureAdapter:
    def __init__(
        self, cfg: Any, factory: AudioCaptureFactory = _default_factory
    ) -> None:
        self._audio_capture = factory(cfg)

    def start(
        self,
        on_chunk: Callable[[AudioChunk], None],
        *,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        parameters = inspect.signature(self._audio_capture.start).parameters

        if "on_error" in parameters:
            self._audio_capture.start(on_chunk, on_error=on_error)
            return

        self._audio_capture.start(on_chunk)

    def stop(self) -> None:
        self._audio_capture.stop()
