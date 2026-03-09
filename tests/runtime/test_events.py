from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from subtitle_runtime.domain.events import RuntimeState, RuntimeStatus, SubtitleEvent


def test_runtime_status_is_healthy_when_starting_or_running() -> None:
    assert RuntimeStatus(state=RuntimeState.STARTING).healthy is True
    assert RuntimeStatus(state=RuntimeState.RUNNING).healthy is True
    assert RuntimeStatus(state=RuntimeState.FAILED).healthy is False


def test_subtitle_event_preserves_translation_metadata() -> None:
    event = SubtitleEvent(
        source_text="hello",
        source_language="English",
        translated_text="你好",
        latency_ms=12.5,
    )

    assert event.source_text == "hello"
    assert event.latency_ms == 12.5
    assert event.translated_text == "你好"
    assert event.source_language == "English"
