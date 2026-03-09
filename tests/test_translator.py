from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from translator import _build_prompt


def test_build_prompt_uses_chinese_instruction_when_target_is_chinese() -> None:
    prompt = _build_prompt("hello", source_lang="en", target_lang="zh")

    assert prompt.startswith("将以下文本翻译为中文")
    assert prompt.endswith("hello")


def test_build_prompt_uses_english_instruction_for_non_chinese_languages() -> None:
    prompt = _build_prompt("bonjour", source_lang="fr", target_lang="en")

    assert prompt.startswith("Translate the following segment into English")
    assert prompt.endswith("bonjour")
