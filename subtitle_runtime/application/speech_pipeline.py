from __future__ import annotations

import time

from subtitle_runtime.application.ports import (
    AudioChunk,
    SpeechTranscriberPort,
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

    def process_segment(self, segment: AudioChunk) -> SubtitleEvent:
        started_at = time.perf_counter()
        transcription = self._transcriber.transcribe(segment)
        translated_text = self._translator.translate(
            transcription.text,
            source_lang=transcription.language,
            target_lang=self._target_lang,
        )
        latency_ms = (time.perf_counter() - started_at) * 1000

        return SubtitleEvent(
            source_text=transcription.text,
            source_language=transcription.language,
            translated_text=translated_text,
            latency_ms=latency_ms,
        )
