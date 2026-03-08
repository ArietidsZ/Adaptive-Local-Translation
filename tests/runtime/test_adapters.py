from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class StubTranslator:
    def __init__(self, cfg):
        self.cfg = cfg

    def translate(self, text, source_lang=None, target_lang=None):
        return f"{source_lang}:{target_lang}:{text}"


def test_package_exports_translator_adapter() -> None:
    adapters = importlib.import_module("subtitle_runtime.adapters")

    assert adapters.TranslatorAdapter.__name__ == "TranslatorAdapter"


def test_asr_adapter_module_import_is_safe_without_optional_dependency() -> None:
    sys.modules.pop("subtitle_runtime.adapters.asr", None)

    module = importlib.import_module("subtitle_runtime.adapters.asr")

    assert module.ASRAdapter.__name__ == "ASRAdapter"


def test_translator_adapter_forwards_language_arguments() -> None:
    translator_module = importlib.import_module("subtitle_runtime.adapters.translator")
    translator_adapter = translator_module.TranslatorAdapter

    adapter = translator_adapter(cfg=object(), factory=StubTranslator)

    value = adapter.translate("hello", source_lang="English", target_lang="zh")

    assert value == "English:zh:hello"
