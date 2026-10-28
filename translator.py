"""
Translation using HY-MT1.5-1.8B-GPTQ-Int4.

Loads the GPTQ-quantized causal LM and translates text segments in real time.
All inference runs on CUDA with torch.no_grad().
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

# ISO 639-1 codes considered "Chinese".
_ZH_CODES: frozenset[str] = frozenset(
    {"zh", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "chinese"}
)

# Human-readable language names for prompts.
_LANG_NAMES: dict[str, str] = {
    "zh": "中文", "zh-cn": "中文", "zh-tw": "中文",
    "en": "English", "de": "German", "fr": "French",
    "es": "Spanish", "ja": "Japanese", "ko": "Korean",
    "pt": "Portuguese", "ru": "Russian", "ar": "Arabic",
    "it": "Italian", "nl": "Dutch", "pl": "Polish",
    "th": "Thai", "vi": "Vietnamese", "tr": "Turkish",
    "id": "Indonesian", "ms": "Malay", "cs": "Czech",
    "ro": "Romanian", "sv": "Swedish", "da": "Danish",
    "fi": "Finnish", "el": "Greek", "hu": "Hungarian",
    "bg": "Bulgarian", "uk": "Ukrainian", "hi": "Hindi",
    "bn": "Bengali", "he": "Hebrew", "fa": "Persian",
}


class Translator:
    """Real-time translator backed by HY-MT1.5-1.8B-GPTQ-Int4."""

    def __init__(self, cfg: Config) -> None:
        logger.info("Loading translation model %s …", cfg.translation_model)

        self._tokenizer = AutoTokenizer.from_pretrained(
            cfg.translation_model,
            trust_remote_code=cfg.translation_trust_remote_code,
            cache_dir=cfg.model_cache_dir,
            local_files_only=cfg.offline_only
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            cfg.translation_model,
            device_map=cfg.translation_device,
            trust_remote_code=cfg.translation_trust_remote_code,
            cache_dir=cfg.model_cache_dir,
            local_files_only=cfg.offline_only,
        )
        self._model.eval()

        self._target_lang = cfg.translation_target_lang
        self._max_new_tokens = cfg.translation_max_new_tokens
        self._gen_kwargs = {
            "top_k": cfg.translation_top_k,
            "top_p": cfg.translation_top_p,
            "temperature": cfg.translation_temperature,
            "repetition_penalty": cfg.translation_repetition_penalty,
            "do_sample": True,
        }
        logger.info("Translation model ready on %s", cfg.translation_device)

    def translate(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str | None = None,
    ) -> str:
        """Translate *text* to *target_lang* (defaults to config target)."""
        target_lang = target_lang or self._target_lang
        prompt = _build_prompt(text, source_lang, target_lang)
        messages = [{"role": "user", "content": prompt}]

        input_ids = self._tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
            return_tensors="pt",
        ).to(self._model.device)

        with torch.no_grad():
            output_ids = self._model.generate(
                input_ids,
                max_new_tokens=self._max_new_tokens,
                **self._gen_kwargs,
            )

        new_tokens = output_ids[0][input_ids.shape[-1]:]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def _build_prompt(text: str, source_lang: str, target_lang: str) -> str:
    target_display = _LANG_NAMES.get(target_lang.lower(), target_lang)
    if source_lang.lower() in _ZH_CODES or target_lang.lower() in _ZH_CODES:
        return (
            f"将以下文本翻译为{target_display}，"
            f"注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
        )
    return (
        f"Translate the following segment into {target_display}, "
        f"without additional explanation.\n\n{text}"
    )
