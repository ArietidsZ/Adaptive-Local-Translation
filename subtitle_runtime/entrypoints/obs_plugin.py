from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import Any

from subtitle_runtime.application.session import SessionController
from subtitle_runtime.domain.events import RuntimeStatus, SubtitleEvent
from subtitle_runtime.entrypoints.cli import build_cli_session


class ResultQueueSink:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()

    def publish(self, event: SubtitleEvent) -> None:
        self._queue.put(event.translated_text)

    def poll_latest(self) -> str | None:
        latest = None

        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                return latest

    def clear(self) -> None:
        self.poll_latest()

    def close(self) -> None:
        return None


class StatusQueueSink:
    def __init__(self) -> None:
        self._queue: queue.Queue[RuntimeStatus] = queue.Queue()

    def publish(self, status: RuntimeStatus) -> None:
        self._queue.put(status)

    def poll_latest(self) -> RuntimeStatus | None:
        latest = None

        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                return latest


@dataclass(frozen=True)
class OBSPluginRuntime:
    session: SessionController
    result_sink: ResultQueueSink
    status_sink: StatusQueueSink


def build_obs_plugin_session(
    cfg: Any,
    *,
    result_sink: ResultQueueSink | None = None,
    status_sink: StatusQueueSink | None = None,
) -> OBSPluginRuntime:
    result_sink = result_sink or ResultQueueSink()
    status_sink = status_sink or StatusQueueSink()

    return OBSPluginRuntime(
        session=build_cli_session(
            cfg,
            subtitle_sink=result_sink,
            status_sink=status_sink,
        ),
        result_sink=result_sink,
        status_sink=status_sink,
    )
