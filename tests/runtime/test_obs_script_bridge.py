from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from subtitle_runtime.domain.events import SubtitleEvent
from subtitle_runtime.entrypoints.obs_plugin import ResultQueueSink


def test_result_queue_sink_keeps_latest_translation() -> None:
    sink = ResultQueueSink()
    sink.publish(SubtitleEvent("hello", "English", "你好", 10.0))
    sink.publish(SubtitleEvent("bye", "English", "再见", 12.0))

    assert sink.poll_latest() == "再见"
