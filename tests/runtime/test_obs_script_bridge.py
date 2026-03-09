from __future__ import annotations

import sys
import types
import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from subtitle_runtime.domain.events import RuntimeState, RuntimeStatus, SubtitleEvent
from subtitle_runtime.entrypoints.obs_plugin import ResultQueueSink


def test_result_queue_sink_keeps_latest_translation() -> None:
    sink = ResultQueueSink()
    sink.publish(SubtitleEvent("hello", "English", "你好", 10.0))
    sink.publish(SubtitleEvent("bye", "English", "再见", 12.0))

    assert sink.poll_latest() == "再见"


def test_timer_tick_stops_pipeline_when_async_failure_is_reported(monkeypatch) -> None:
    class FakeOBSModule:
        OBS_TEXT_DEFAULT = 0

        def timer_remove(self, callback) -> None:
            del callback

    class FakeSession:
        def __init__(self) -> None:
            self.stop_calls = 0

        def stop(self) -> None:
            self.stop_calls += 1

    class FakeResultSink:
        def __init__(self) -> None:
            self.clear_calls = 0

        def poll_latest(self) -> str | None:
            return None

        def clear(self) -> None:
            self.clear_calls += 1

    class FakeStatusSink:
        def poll_latest(self) -> RuntimeStatus:
            return RuntimeStatus(state=RuntimeState.FAILED)

    class FakeTextSink:
        def __init__(self) -> None:
            self.clear_calls = 0

        def update(self, text: str) -> None:
            del text
            pytest.fail("text should not be updated after async failure")

        def clear(self) -> None:
            self.clear_calls += 1

    monkeypatch.setitem(sys.modules, "obspython", FakeOBSModule())
    obs_script = importlib.import_module("obs_script")

    session = FakeSession()
    result_sink = FakeResultSink()
    text_sink = FakeTextSink()
    obs_script._runtime = types.SimpleNamespace(
        session=session,
        result_sink=result_sink,
        status_sink=FakeStatusSink(),
    )
    obs_script._text_sink = text_sink

    obs_script._timer_tick()

    assert session.stop_calls == 1
    assert result_sink.clear_calls == 1
    assert text_sink.clear_calls == 1
    assert obs_script._runtime is None
    assert obs_script._text_sink is None
