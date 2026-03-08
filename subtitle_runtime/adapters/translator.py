from __future__ import annotations

from typing import Any, Protocol

from translator import Translator


class TranslatorFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


class TranslatorAdapter:
    def __init__(self, cfg: Any, factory: TranslatorFactory = Translator) -> None:
        self._translator = factory(cfg)

    def translate(
        self,
        text: str,
        source_lang: str = "",
        target_lang: str | None = None,
    ) -> str:
        return self._translator.translate(
            text,
            source_lang=source_lang,
            target_lang=target_lang,
        )
