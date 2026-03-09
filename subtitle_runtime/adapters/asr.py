from __future__ import annotations

from typing import Any, Protocol

from subtitle_runtime.application.ports import AudioChunk


class ASRFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


def _default_factory(cfg: Any) -> Any:
    from asr import ASR

    return ASR(cfg)


class ASRAdapter:
    def __init__(self, cfg: Any, factory: ASRFactory = _default_factory) -> None:
        self._asr = factory(cfg)

    def transcribe(self, segment: AudioChunk) -> str:
        return self._asr.transcribe(segment)
