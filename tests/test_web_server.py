from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from subtitle_runtime.domain.events import RuntimeState, RuntimeStatus, SubtitleEvent
from web_server import RuntimeStatusSink, RuntimeSubtitleSink


def test_status_sink_broadcasts_runtime_state() -> None:
    messages = []
    sink = RuntimeStatusSink(lambda msg: messages.append(msg))

    sink.publish(RuntimeStatus(state=RuntimeState.RUNNING))

    assert messages == [{"type": "status", "state": "running"}]


def test_subtitle_sink_broadcasts_websocket_result_payload() -> None:
    messages = []
    sink = RuntimeSubtitleSink(lambda msg: messages.append(msg))

    sink.publish(
        SubtitleEvent(
            source_text="hello",
            source_language="English",
            translated_text="你好",
            latency_ms=12.5,
        )
    )

    assert messages == [
        {
            "type": "result",
            "original": "hello",
            "translation": "你好",
            "language": "English",
            "latency_ms": 12.5,
        }
    ]
