"""Deterministic lifecycle tests with real blocking stop threads, no models/devices."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

import web_server
from subtitle_runtime.domain.events import RuntimeState


class BlockingSession:
    def __init__(self, state=RuntimeState.STOPPED):
        self.status = SimpleNamespace(state=state)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.stop_calls = 0
        self.start_calls = 0

    def stop(self):
        self.stop_calls += 1
        self.entered.set()
        assert self.release.wait(5), "test did not release stop"

    def start(self):
        self.start_calls += 1
        self.status.state = RuntimeState.RUNNING


async def entered(session):
    assert await asyncio.to_thread(session.entered.wait, 2)


def test_cancelled_stop_retains_worker_and_serializes_restart(monkeypatch):
    async def scenario():
        dashboard = web_server.WebDashboard()
        old = BlockingSession()
        new = BlockingSession()
        dashboard._session = old
        builds = []
        monkeypatch.setattr(web_server, "build_cli_session",
                            lambda *a, **kw: builds.append(new) or new)
        stopping = asyncio.create_task(dashboard._stop_engine())
        await entered(old)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert dashboard._session is old
        owned = dashboard._stop_task
        restarting = asyncio.create_task(dashboard._start_engine())
        await asyncio.sleep(0)
        assert dashboard._stop_task is owned
        assert not builds
        assert old.stop_calls == 1
        old.release.set()
        await asyncio.wait_for(restarting, 2)
        assert builds == [new]
        assert dashboard._session is new
        assert old.stop_calls == 1
        assert new.start_calls == 1
    asyncio.run(scenario())


def test_cancelled_restart_never_builds_and_cleanup_joins_same_stop(monkeypatch):
    async def scenario():
        dashboard = web_server.WebDashboard()
        old = BlockingSession()
        dashboard._session = old
        builds = []
        monkeypatch.setattr(web_server, "build_cli_session",
                            lambda *a, **kw: builds.append(True))
        restart = asyncio.create_task(dashboard._start_engine())
        await entered(old)
        restart.cancel()
        with pytest.raises(asyncio.CancelledError):
            await restart
        cleanup = asyncio.create_task(dashboard._cleanup(dashboard._app))
        await asyncio.sleep(0)
        late_start = asyncio.create_task(dashboard._start_engine())
        await asyncio.sleep(0)
        assert old.stop_calls == 1
        assert not builds
        old.release.set()
        await asyncio.wait_for(asyncio.gather(cleanup, late_start), 2)
        assert dashboard._session is None
        assert not builds
        assert dashboard._stop_task is None
    asyncio.run(scenario())


def test_concurrent_restarts_only_create_one_replacement(monkeypatch):
    async def scenario():
        dashboard = web_server.WebDashboard()
        old, new = BlockingSession(), BlockingSession()
        dashboard._session = old
        builds = []
        monkeypatch.setattr(web_server, "build_cli_session",
                            lambda *a, **kw: builds.append(new) or new)
        first = asyncio.create_task(dashboard._start_engine())
        await entered(old)
        second = asyncio.create_task(dashboard._start_engine())
        await asyncio.sleep(0)
        old.release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 2)
        assert builds == [new]
        assert new.start_calls == 1
        assert old.stop_calls == 1
    asyncio.run(scenario())


def test_cleanup_failure_keeps_session_and_can_retry():
    async def scenario():
        dashboard = web_server.WebDashboard()
        session = BlockingSession()
        failures = [True]
        def stop():
            session.stop_calls += 1
            if failures:
                failures.pop()
                raise RuntimeError("audio still alive")
        session.stop = stop
        dashboard._session = session
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await dashboard._cleanup(dashboard._app)
        assert dashboard._session is session
        assert dashboard._stop_task is None
        await dashboard._cleanup(dashboard._app)
        assert dashboard._session is None
        assert session.stop_calls == 2
    asyncio.run(scenario())


def test_app_runner_cleanup_stops_owned_session():
    async def scenario():
        dashboard = web_server.WebDashboard()
        session = BlockingSession(RuntimeState.RUNNING)
        session.release.set()
        dashboard._session = session
        runner = web_server.web.AppRunner(dashboard._app)
        await runner.setup()
        assert dashboard._loop is asyncio.get_running_loop()
        await runner.cleanup()
        assert session.stop_calls == 1
        assert dashboard._session is None
        assert dashboard._closing
    asyncio.run(scenario())


def test_cancelled_stop_failure_is_observed_and_retryable():
    async def scenario():
        dashboard = web_server.WebDashboard()
        session = BlockingSession()
        fail = [True]
        def stop():
            session.stop_calls += 1
            session.entered.set()
            assert session.release.wait(5)
            if fail:
                fail.pop()
                raise RuntimeError("stop failed after cancellation")
        session.stop = stop
        dashboard._session = session
        request = asyncio.create_task(dashboard._stop_engine())
        await entered(session)
        owned = dashboard._stop_task
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        session.release.set()
        # The retained failure is consumed without discarding session ownership.
        await dashboard._stop_engine()
        assert owned.done()
        assert dashboard._session is session
        assert dashboard._stop_task is None
        await dashboard._stop_engine()
        assert dashboard._session is None
        assert session.stop_calls == 2
    asyncio.run(scenario())


def test_handshake_finishing_during_shutdown_is_closed(monkeypatch):
    async def scenario():
        dashboard = web_server.WebDashboard()
        class Socket:
            closed = False
            async def prepare(self, request):
                dashboard._closing = True
            async def close(self, **kwargs):
                self.closed = True
        socket = Socket()
        monkeypatch.setattr(web_server.web, "WebSocketResponse", lambda: socket)
        request = SimpleNamespace(scheme="http", host="127.0.0.1", headers={})
        assert await dashboard._ws_handler(request) is socket
        assert socket.closed
        assert not dashboard._clients
    asyncio.run(scenario())


def test_initial_status_send_failure_removes_client(monkeypatch):
    async def scenario():
        dashboard = web_server.WebDashboard()
        dashboard._session = BlockingSession()
        class Socket:
            async def prepare(self, request):
                pass
            async def send_json(self, message):
                raise ConnectionError("peer disappeared")
        socket = Socket()
        monkeypatch.setattr(web_server.web, "WebSocketResponse", lambda: socket)
        request = SimpleNamespace(scheme="http", host="127.0.0.1", headers={})
        with pytest.raises(ConnectionError):
            await dashboard._ws_handler(request)
        assert not dashboard._clients
    asyncio.run(scenario())


def test_shutdown_delivers_flushed_tail_before_socket_close():
    async def scenario():
        dashboard = web_server.WebDashboard()
        dashboard._loop = asyncio.get_running_loop()
        events = []
        class Socket:
            async def send_json(self, message):
                await asyncio.sleep(0)
                events.append(message)
            async def close(self, **kwargs):
                events.append("closed")
        dashboard._clients.add(Socket())
        session = BlockingSession()
        session.stop = lambda: dashboard._broadcast(
            {"type": "result", "original": "tail"}
        )
        dashboard._session = session
        await dashboard._shutdown(dashboard._app)
        assert events == [{"type": "result", "original": "tail"}, "closed"]
        assert not dashboard._pending_broadcasts
        assert dashboard._session is None
        dashboard._broadcast({"late": True})
        await asyncio.sleep(0)
        assert events[-1] == "closed"
    asyncio.run(scenario())


def test_shutdown_bounds_stalled_send_and_closes_socket(caplog):
    async def scenario():
        dashboard = web_server.WebDashboard()
        dashboard._loop = asyncio.get_running_loop()
        dashboard._drain_timeout = 0.01
        events = []
        class Socket:
            async def send_json(self, message):
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append("send cancelled")
            async def close(self, **kwargs):
                events.append("closed")
        dashboard._clients.add(Socket())
        dashboard._broadcast({"type": "result"})
        await asyncio.wait_for(dashboard._shutdown(dashboard._app), 1)
        await asyncio.sleep(0)
        assert "closed" in events
        assert "send cancelled" in events
        assert not dashboard._pending_broadcasts
        assert "Timed out draining" in caplog.text
    asyncio.run(scenario())


def test_completed_broadcast_callback_does_not_deadlock(monkeypatch):
    from concurrent.futures import Future
    dashboard = web_server.WebDashboard()
    dashboard._loop = SimpleNamespace(is_closed=lambda: False)
    def completed(coro, loop):
        coro.close()
        future = Future()
        future.set_result(None)
        return future
    monkeypatch.setattr(web_server.asyncio, "run_coroutine_threadsafe", completed)
    dashboard._broadcast({"type": "result"})
    assert not dashboard._pending_broadcasts


def test_loop_close_during_broadcast_submission_leaves_no_coroutine(monkeypatch):
    dashboard = web_server.WebDashboard()
    dashboard._loop = SimpleNamespace(is_closed=lambda: False)
    submitted = []
    def rejected(coro, loop):
        submitted.append(coro)
        raise RuntimeError("Event loop is closed")
    monkeypatch.setattr(web_server.asyncio, "run_coroutine_threadsafe", rejected)
    dashboard._broadcast({"type": "result"})
    assert submitted[0].cr_frame is None
    assert not dashboard._pending_broadcasts


def test_failed_shutdown_keeps_session_for_cleanup_without_reopening_broadcasts():
    async def scenario():
        dashboard = web_server.WebDashboard()
        dashboard._loop = asyncio.get_running_loop()
        session = BlockingSession()
        calls = []
        def stop():
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("audio still stopping")
            dashboard._broadcast({"type": "result", "original": "retry tail"})
        session.stop = stop
        dashboard._session = session
        await dashboard._shutdown(dashboard._app)
        assert dashboard._session is session
        assert dashboard._broadcasts_closed
        await dashboard._cleanup(dashboard._app)
        assert dashboard._session is None
        assert not dashboard._pending_broadcasts
        assert len(calls) == 2
    asyncio.run(scenario())
