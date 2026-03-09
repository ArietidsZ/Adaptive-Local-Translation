from __future__ import annotations

import time

from subtitle_runtime.application.ports import (
    AudioChunk,
    SpeechTranscriberPort,
    TranscriptionResult,
    TextTranslatorPort,
)
from subtitle_runtime.domain.events import SubtitleEvent


class SpeechPipeline:
    def __init__(
        self,
        transcriber: SpeechTranscriberPort,
        translator: TextTranslatorPort,
        *,
        target_lang: str,
    ) -> None:
        self._transcriber = transcriber
        self._translator = translator
        self._target_lang = target_lang

    def process_segment(self, segment: AudioChunk) -> SubtitleEvent | None:
        started_at = time.perf_counter()
        transcription = self._transcriber.transcribe(segment)
        source_text, source_language = self._unpack_transcription(transcription)

        if not source_text:
            return None

        translated_text = self._translator.translate(
            source_text,
            source_lang=source_language,
            target_lang=self._target_lang,
        )
        latency_ms = (time.perf_counter() - started_at) * 1000

        return SubtitleEvent(
            source_text=source_text,
            source_language=source_language,
            translated_text=translated_text,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _unpack_transcription(
        transcription: str | TranscriptionResult,
    ) -> tuple[str, str]:
        if isinstance(transcription, str):
            return transcription.strip(), ""

        return transcription.text.strip(), transcription.language
