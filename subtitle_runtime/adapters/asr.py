from __future__ import annotations

from typing import Any, Protocol

from subtitle_runtime.application.ports import AudioChunk

from asr import ASR


class ASRFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


class ASRAdapter:
    def __init__(self, cfg: Any, factory: ASRFactory = ASR) -> None:
        self._asr = factory(cfg)

    def transcribe(self, segment: AudioChunk) -> str:
        return self._asr.transcribe(segment)
