from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

pytest_plugins = ("aiohttp.pytest_plugin",)

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import web_server
from subtitle_runtime.domain.events import RuntimeState, RuntimeStatus, SubtitleEvent
from web_server import RuntimeStatusSink, RuntimeSubtitleSink, WebDashboard


@dataclass
class FakeSession:
    status: RuntimeStatus

    def __post_init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class MutatingWebSocket:
    def __init__(self, dashboard: WebDashboard, *, remove_self: bool = False) -> None:
        self._dashboard = dashboard
        self._remove_self = remove_self
        self.messages = []

    async def send_json(self, msg) -> None:
        self.messages.append(msg)
        if self._remove_self:
            self._dashboard._clients.discard(self)
        await asyncio.sleep(0)


class StreamingFakeSession(FakeSession):
    def __init__(self, status: RuntimeStatus, *, subtitle_sink, status_sink) -> None:
        super().__init__(status)
        self._subtitle_sink = subtitle_sink
        self._status_sink = status_sink

    def start(self) -> None:
        super().start()
        self._status_sink.publish(RuntimeStatus(state=RuntimeState.STARTING))
        self._status_sink.publish(RuntimeStatus(state=RuntimeState.RUNNING))
        self._subtitle_sink.publish(
            SubtitleEvent(
                source_text="hello",
                source_language="English",
                translated_text="你好",
                latency_ms=12.5,
            )
        )


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


def test_broadcast_uses_client_snapshot_when_client_disconnects(monkeypatch) -> None:
    async def scenario() -> None:
        dashboard = WebDashboard()
        dashboard._loop = asyncio.get_running_loop()
        first = MutatingWebSocket(dashboard, remove_self=True)
        second = MutatingWebSocket(dashboard)
        dashboard._clients = {first, second}
        tasks = []

        def fake_run_coroutine_threadsafe(coro, loop):
            task = loop.create_task(coro)
            tasks.append(task)
            return task

        monkeypatch.setattr(
            web_server.asyncio,
            "run_coroutine_threadsafe",
            fake_run_coroutine_threadsafe,
        )

        dashboard._broadcast({"type": "status", "state": "running"})

        await tasks[0]

        assert first.messages == [{"type": "status", "state": "running"}]
        assert second.messages == [{"type": "status", "state": "running"}]

    asyncio.run(scenario())


def test_stop_message_offloads_session_stop_from_event_loop(monkeypatch) -> None:
    async def scenario() -> None:
        dashboard = WebDashboard()
        session = FakeSession(RuntimeStatus(state=RuntimeState.RUNNING))
        dashboard._session = session
        to_thread_calls = []

        async def fake_to_thread(func, *args, **kwargs):
            to_thread_calls.append((func, args, kwargs))
            return func(*args, **kwargs)

        monkeypatch.setattr(web_server.asyncio, "to_thread", fake_to_thread)

        await dashboard._handle_client_msg(object(), '{"type": "stop"}')

        assert len(to_thread_calls) == 1
        assert to_thread_calls[0][0].__self__ is session
        assert to_thread_calls[0][0].__func__ is FakeSession.stop
        assert session.stop_calls == 1
        assert dashboard._session is None

    asyncio.run(scenario())


def test_start_message_offloads_previous_session_stop(monkeypatch) -> None:
    async def scenario() -> None:
        dashboard = WebDashboard()
        previous_session = FakeSession(RuntimeStatus(state=RuntimeState.STOPPED))
        replacement_session = FakeSession(RuntimeStatus(state=RuntimeState.STARTING))
        dashboard._session = previous_session
        to_thread_calls = []

        async def fake_to_thread(func, *args, **kwargs):
            to_thread_calls.append((func, args, kwargs))
            return func(*args, **kwargs)

        monkeypatch.setattr(web_server.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(
            web_server,
            "build_cli_session",
            lambda cfg, *, subtitle_sink, status_sink: replacement_session,
        )

        await dashboard._handle_client_msg(object(), '{"type": "start"}')

        assert len(to_thread_calls) == 1
        assert to_thread_calls[0][0].__self__ is previous_session
        assert to_thread_calls[0][0].__func__ is FakeSession.stop
        assert previous_session.stop_calls == 1
        assert replacement_session.start_calls == 1
        assert dashboard._session is replacement_session

    asyncio.run(scenario())


async def test_websocket_start_flow_emits_runtime_status_and_results(
    aiohttp_client, monkeypatch
) -> None:
    dashboard = WebDashboard()
    dashboard._loop = asyncio.get_running_loop()

    def fake_build_cli_session(cfg, *, subtitle_sink, status_sink):
        return StreamingFakeSession(
            RuntimeStatus(state=RuntimeState.STOPPED),
            subtitle_sink=subtitle_sink,
            status_sink=status_sink,
        )

    monkeypatch.setattr(web_server, "build_cli_session", fake_build_cli_session)

    client = await aiohttp_client(dashboard._app)
    ws = await client.ws_connect("/ws")

    await ws.send_json({"type": "start"})

    received_status = await ws.receive_json(timeout=1)
    received_running_status = await ws.receive_json(timeout=1)
    received_result = await ws.receive_json(timeout=1)

    assert received_status["type"] == "status"
    assert received_status["state"] in {"starting", "running", "failed"}
    assert received_running_status == {"type": "status", "state": "running"}
    assert set(received_result) >= {
        "type",
        "original",
        "translation",
        "language",
        "latency_ms",
    }

    await ws.close()
