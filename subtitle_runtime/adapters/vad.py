from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from subtitle_runtime.application.ports import AudioChunk


class VADFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


def _default_factory(cfg: Any) -> Any:
    from vad import VAD

    return VAD(cfg)


class VADAdapter:
    def __init__(self, cfg: Any, factory: VADFactory = _default_factory) -> None:
        self._vad = factory(cfg)

    def process_chunk(
        self,
        chunk: AudioChunk,
        on_speech: Callable[[AudioChunk], None],
    ) -> None:
        self._vad.process_chunk(chunk, on_speech)

    def flush(self, on_speech: Callable[[AudioChunk], None]) -> None:
        self._vad.flush(on_speech)
