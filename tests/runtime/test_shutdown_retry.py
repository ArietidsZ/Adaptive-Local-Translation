from __future__ import annotations

import asyncio
import queue
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from subtitle_runtime.application.audio_ingress import AudioIngress
from subtitle_runtime.application.session import SessionController
from subtitle_runtime.domain.events import RuntimeState
from subtitle_runtime.entrypoints.cli import _QueuedAudioSource
from web_server import WebDashboard


class Audio:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    def start(self, on_chunk, *, on_error=None):
        self.callback = on_chunk

    def stop(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("capture stop failed")


class Segmenter:
    def __init__(self, failures=0):
        self.calls = 0
        self.failures = failures

    def process_chunk(self, chunk, callback):
        pass

    def flush(self, callback):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("flush failed")


def make_session(audio, segmenter, publish=lambda status: None):
    return SessionController(
        audio_source=audio,
        speech_segmenter=segmenter,
        speech_pipeline=SimpleNamespace(process_segment=lambda value: None),
        subtitle_sink=SimpleNamespace(publish=lambda value: None),
        status_sink=SimpleNamespace(publish=publish),
    )


def test_audio_failure_retries_without_premature_flush_or_false_success():
    audio, segmenter = Audio(1), Segmenter()
    session = make_session(audio, segmenter)
    session.start()
    with pytest.raises(RuntimeError, match="capture"):
        session.stop()
    assert segmenter.calls == 0
    with pytest.raises(RuntimeError, match="shutdown"):
        session.start()
    session.stop()
    session.stop()
    assert (audio.calls, segmenter.calls) == (2, 1)
    assert session.status.state is RuntimeState.FAILED


def test_flush_retry_does_not_repeat_successful_audio_cleanup():
    audio, segmenter = Audio(), Segmenter(1)
    session = make_session(audio, segmenter)
    session.start()
    with pytest.raises(RuntimeError, match="flush"):
        session.stop()
    session.stop()
    session.stop()
    assert (audio.calls, segmenter.calls) == (1, 2)


def test_competing_stop_never_claims_completion():
    entered, release = threading.Event(), threading.Event()

    class BlockingAudio(Audio):
        def stop(self):
            entered.set()
            assert release.wait(3)
            super().stop()

    audio, segmenter = BlockingAudio(), Segmenter()
    session = make_session(audio, segmenter)
    session.start()
    worker = threading.Thread(target=session.stop)
    worker.start()
    try:
        assert entered.wait(3)
        with pytest.raises(RuntimeError, match="in progress"):
            session.stop()
        assert segmenter.calls == 0
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert session._stopped


def test_reentrant_observer_does_not_deadlock():
    audio, segmenter = Audio(), Segmenter()

    def publish(status):
        if status.state is RuntimeState.STOPPING:
            with pytest.raises(RuntimeError, match="in progress"):
                session.stop()

    session = make_session(audio, segmenter, publish)
    session.start()
    session.stop()
    assert session._stopped


def test_throwing_observer_does_not_hold_shutdown_ownership():
    def publish(status):
        if status.state is RuntimeState.STOPPING:
            raise RuntimeError("observer")

    audio, segmenter = Audio(), Segmenter()
    session = make_session(audio, segmenter, publish)
    session.start()
    with pytest.raises(RuntimeError, match="observer"):
        session.stop()
    session.stop()
    assert session._stopped
    assert (audio.calls, segmenter.calls) == (1, 1)


def test_queue_failure_closes_ingress_drains_and_can_retry():
    audio = Audio(1)
    ingress = AudioIngress(4)
    source = _QueuedAudioSource(audio, ingress)
    seen = []
    source.start(seen.append)
    audio.callback(np.array([1]))
    with pytest.raises(RuntimeError, match="capture"):
        source.stop()
    assert source._drain_thread is None
    audio.callback(np.array([2]))
    with pytest.raises(queue.Empty):
        ingress.pop_nowait()
    assert len(seen) == 1
    source.stop()
    assert audio.calls == 2


def test_dashboard_real_session_retries_before_discarding():
    audio, segmenter = Audio(1), Segmenter()
    session = make_session(audio, segmenter)
    session.start()
    dashboard = WebDashboard()
    dashboard._session = session
    asyncio.run(dashboard._stop_engine())
    assert dashboard._session is session
    asyncio.run(dashboard._stop_engine())
    assert dashboard._session is None
    assert (audio.calls, segmenter.calls) == (2, 1)


def test_repeated_capture_failure_never_returns_success():
    audio, segmenter = Audio(100), Segmenter()
    session = make_session(audio, segmenter)
    session.start()
    for _ in range(3):
        with pytest.raises(RuntimeError, match="capture"):
            session.stop()
    assert not session._stopped
    assert segmenter.calls == 0


def test_worker_error_callback_can_finish_while_owner_stops():
    class CallbackAudio(Audio):
        def stop(self):
            worker = threading.Thread(
                target=lambda: session._handle_error(RuntimeError("worker"))
            )
            worker.start()
            worker.join(2)
            assert not worker.is_alive()
            super().stop()

    audio, segmenter = CallbackAudio(), Segmenter()
    session = make_session(audio, segmenter)
    session.start()
    session.stop()
    assert session._stopped
    assert session.status.state is RuntimeState.FAILED


def test_drain_self_stop_requires_external_join():
    audio = Audio()
    source = _QueuedAudioSource(audio, AudioIngress(4))
    returned = threading.Event()
    errors = []

    def on_chunk(chunk):
        try:
            source.stop()
        except RuntimeError as error:
            errors.append(str(error))
        finally:
            returned.set()

    source.start(on_chunk)
    audio.callback(np.array([1]))
    assert returned.wait(3)
    assert errors == ["Audio drain shutdown needs an external join"]
    assert source._drain_thread is not None
    source.stop()
    assert source._drain_thread is None


def test_join_failure_keeps_worker_reference_for_retry():
    class Worker:
        calls = 0

        def join(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("join failed")

    source = _QueuedAudioSource(Audio(), AudioIngress(4))
    worker = Worker()
    source._drain_thread = worker
    with pytest.raises(RuntimeError, match="join failed"):
        source.stop()
    assert source._drain_thread is worker
    source.stop()
    assert source._drain_thread is None


def test_stopped_observer_failure_does_not_repeat_completed_cleanup():
    def publish(status):
        if status.state is RuntimeState.STOPPED:
            raise RuntimeError("stopped observer")

    audio, segmenter = Audio(), Segmenter()
    session = make_session(audio, segmenter, publish)
    session.start()
    with pytest.raises(RuntimeError, match="stopped observer"):
        session.stop()
    session.stop()
    assert (audio.calls, segmenter.calls) == (1, 1)
