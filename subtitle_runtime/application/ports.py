from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, TypeAlias, overload

import numpy as np
from numpy.typing import NDArray

from subtitle_runtime.domain.events import RuntimeStatus, SubtitleEvent


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


class AudioSourcePort(Protocol):
    @overload
    def start(self, on_chunk: Callable[[AudioChunk], None]) -> None: ...

    @overload
    def start(
        self,
        on_chunk: Callable[[AudioChunk], None],
        *,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None: ...

    def stop(self) -> None: ...


class SpeechSegmenterPort(Protocol):
    def process_chunk(
        self,
        chunk: AudioChunk,
        on_speech: Callable[[AudioChunk], None],
    ) -> None: ...

    def flush(self, on_speech: Callable[[AudioChunk], None]) -> None: ...


class SpeechPipelinePort(Protocol):
    def process_segment(self, segment: AudioChunk) -> SubtitleEvent | None: ...


class SubtitleSinkPort(Protocol):
    def publish(self, event: SubtitleEvent) -> None: ...


class StatusSinkPort(Protocol):
    def publish(self, status: RuntimeStatus) -> None: ...
