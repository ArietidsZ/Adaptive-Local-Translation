"""
Speech-to-text using Qwen3-ASR.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import torch
from qwen_asr import Qwen3ASRModel

from model_loading import resolve_model_directory

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

_LANGUAGE_ALIASES: dict[str, str] = {
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
    "zh-hans": "Chinese",
    "zh-hant": "Chinese",
    "chinese": "Chinese",
    "en": "English",
    "english": "English",
    "ja": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
    "de": "German",
    "german": "German",
    "fr": "French",
    "french": "French",
    "es": "Spanish",
    "spanish": "Spanish",
    "it": "Italian",
    "italian": "Italian",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "ru": "Russian",
    "russian": "Russian",
    "ar": "Arabic",
    "arabic": "Arabic",
    "th": "Thai",
    "thai": "Thai",
    "vi": "Vietnamese",
    "vietnamese": "Vietnamese",
    "tr": "Turkish",
    "turkish": "Turkish",
    "id": "Indonesian",
    "indonesian": "Indonesian",
    "ms": "Malay",
    "malay": "Malay",
    "nl": "Dutch",
    "dutch": "Dutch",
    "sv": "Swedish",
    "swedish": "Swedish",
    "da": "Danish",
    "danish": "Danish",
    "fi": "Finnish",
    "finnish": "Finnish",
    "pl": "Polish",
    "polish": "Polish",
    "cs": "Czech",
    "czech": "Czech",
    "fa": "Persian",
    "persian": "Persian",
    "el": "Greek",
    "greek": "Greek",
    "hu": "Hungarian",
    "hungarian": "Hungarian",
    "ro": "Romanian",
    "romanian": "Romanian",
    "mk": "Macedonian",
    "macedonian": "Macedonian",
    "hi": "Hindi",
    "hindi": "Hindi",
    "fil": "Filipino",
    "filipino": "Filipino",
    "yue": "Cantonese",
    "cantonese": "Cantonese",
}


def _resolve_dtype(name: str) -> torch.dtype:
    value = name.strip().lower()
    if value in {"float16", "fp16", "half"}:
        return torch.float16
    if value in {"bfloat16", "bf16"}:
        return torch.bfloat16
    if value in {"float32", "fp32", "full"}:
        return torch.float32
    logger.warning("Unknown ASR compute type '%s', fallback to float16", name)
    return torch.float16


def _resolve_device_map(device: str) -> str:
    value = device.strip().lower()
    if value == "cuda":
        return "cuda:0"
    return device


def _resolve_language(language: str | None) -> str | None:
    if language is None:
        return None
    value = language.strip().lower()
    if not value:
        return None
    if value in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[value]
    return value[:1].upper() + value[1:]


class ASR:
    """Wraps Qwen3-ASR for single-shot transcription of speech segments."""

    def __init__(self, cfg: Config) -> None:
        dtype = _resolve_dtype(cfg.asr_compute_type)
        device_map = _resolve_device_map(cfg.asr_device)
        language = _resolve_language(cfg.asr_language)

        logger.info(
            "Loading Qwen3-ASR %s on %s (%s) …",
            cfg.asr_model,
            device_map,
            dtype,
        )
        self._model = Qwen3ASRModel.from_pretrained(
            resolve_model_directory(cfg.asr_model, cfg),
            local_files_only=True,
            dtype=dtype,
            device_map=device_map,
            max_new_tokens=cfg.asr_max_new_tokens,
        )
        self._language = language
        logger.info("ASR ready")

    def transcribe(self, audio: np.ndarray) -> str:
        """Return recognised text for a 16 kHz float32 speech segment."""
        result = self._model.transcribe(
            audio=(audio, 16_000),
            language=self._language,
        )

        text = ""
        lang = self._language or "auto"
        if result:
            text = result[0].text.strip()
            if result[0].language:
                lang = result[0].language

        if text:
            logger.debug("ASR [%s]: %s", lang, text)
        return text
