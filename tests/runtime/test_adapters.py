from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from subtitle_runtime.adapters.translator import TranslatorAdapter


class StubTranslator:
    def __init__(self, cfg):
        self.cfg = cfg

    def translate(self, text, source_lang=None, target_lang=None):
        return f"{source_lang}:{target_lang}:{text}"


def test_translator_adapter_forwards_language_arguments() -> None:
    adapter = TranslatorAdapter(cfg=object(), factory=StubTranslator)

    value = adapter.translate("hello", source_lang="English", target_lang="zh")

    assert value == "English:zh:hello"
