from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from subtitle_runtime.application.ports import AudioChunk

from vad import VAD


class VADFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


class VADAdapter:
    def __init__(self, cfg: Any, factory: VADFactory = VAD) -> None:
        self._vad = factory(cfg)

    def process_chunk(
        self,
        chunk: AudioChunk,
        on_speech: Callable[[AudioChunk], None],
    ) -> None:
        self._vad.process_chunk(chunk, on_speech)

    def flush(self, on_speech: Callable[[AudioChunk], None]) -> None:
        self._vad.flush(on_speech)
