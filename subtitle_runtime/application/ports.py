from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

import numpy as np
from numpy.typing import NDArray


AudioChunk: TypeAlias = NDArray[np.float32]


@dataclass(frozen=True)
class IngressReport:
    dropped_chunks: int = 0


class AudioIngressPort(Protocol):
    def push(self, chunk: AudioChunk) -> IngressReport: ...

    def pop_nowait(self) -> AudioChunk: ...


class TranscriptionResult(Protocol):
    text: str
    language: str


class SpeechTranscriberPort(Protocol):
    def transcribe(self, segment: AudioChunk) -> str | TranscriptionResult: ...


class TextTranslatorPort(Protocol):
    def translate(
        self,
        text: str,
        source_lang: str = "",
        target_lang: str | None = None,
    ) -> str: ...
