from types import SimpleNamespace

import pytest

import audio


class FakeThread:
    def __init__(self, **kwargs):
        self.alive = False
        self.joins = []
        self.stop_on_join = True
        self.fail_start = False

    def start(self):
        if self.fail_start:
            raise RuntimeError("controlled start failure")
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.joins.append(timeout)
        if self.stop_on_join:
            self.alive = False


@pytest.fixture
def capture(monkeypatch):
    workers = []

    def factory(**kwargs):
        worker = FakeThread(**kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(audio.threading, "Thread", factory)
    return audio.AudioCapture(SimpleNamespace()), workers


def test_normal_stop_and_restart(capture):
    owner, workers = capture
    owner.start(lambda pcm: None)
    owner.start(lambda pcm: None)
    assert len(workers) == 1
    owner.stop()
    assert workers[0].joins == [3.0]
    assert owner._thread is None
    owner.stop()
    owner.start(lambda pcm: None)
    assert len(workers) == 2
    owner.stop()


def test_timeout_retains_worker_and_blocks_restart(capture):
    owner, workers = capture
    owner.start(lambda pcm: None)
    worker = workers[0]
    worker.stop_on_join = False
    with pytest.raises(TimeoutError, match="did not stop"):
        owner.stop()
    assert owner._thread is worker
    assert not owner._running
    with pytest.raises(RuntimeError, match="previous audio"):
        owner.start(lambda pcm: None)
    assert len(workers) == 1
    worker.stop_on_join = True
    owner.stop()
    assert worker.joins == [3.0, 3.0]
    assert owner._thread is None
    owner.start(lambda pcm: None)
    assert len(workers) == 2
    owner.stop()


def test_completed_worker_can_be_replaced(capture):
    owner, workers = capture
    owner.start(lambda pcm: None)
    workers[0].alive = False
    owner._running = False
    owner.start(lambda pcm: None)
    assert len(workers) == 2
    owner.stop()


def test_self_stop_retains_ownership(capture, monkeypatch):
    owner, workers = capture
    owner.start(lambda pcm: None)
    worker = workers[0]
    with monkeypatch.context() as local:
        local.setattr(audio.threading, "current_thread", lambda: worker)
        with pytest.raises(RuntimeError, match="join itself"):
            owner.stop()
    assert owner._thread is worker
    assert worker.joins == []
    owner.stop()
    assert owner._thread is None


def test_start_failure_rolls_back_state(monkeypatch):
    worker = FakeThread()
    worker.fail_start = True
    monkeypatch.setattr(audio.threading, "Thread", lambda **kwargs: worker)
    owner = audio.AudioCapture(SimpleNamespace())
    with pytest.raises(RuntimeError, match="controlled start"):
        owner.start(lambda pcm: None)
    assert owner._thread is None
    assert not owner._running
    owner.stop()


def test_join_does_not_hold_lifecycle_lock(capture):
    owner, workers = capture
    owner.start(lambda pcm: None)
    worker = workers[0]

    def join(timeout):
        assert owner._lifecycle_lock.acquire(blocking=False)
        owner._lifecycle_lock.release()
        worker.alive = False

    worker.join = join
    owner.stop()
    assert owner._thread is None


def test_old_stop_does_not_clear_replacement(capture):
    owner, workers = capture
    owner.start(lambda pcm: None)
    old = workers[0]

    def join(timeout):
        old.alive = False
        owner.start(lambda pcm: None)

    old.join = join
    owner.stop()
    assert len(workers) == 2
    assert owner._thread is workers[1]
    assert owner._running
    owner.stop()


def test_thread_constructor_failure_does_not_mark_running(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("controlled construction failure")

    monkeypatch.setattr(audio.threading, "Thread", fail)
    owner = audio.AudioCapture(SimpleNamespace())
    with pytest.raises(RuntimeError, match="controlled construction"):
        owner.start(lambda pcm: None)
    assert not owner._running
    assert owner._thread is None
    owner.stop()
