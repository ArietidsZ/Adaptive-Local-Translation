from __future__ import annotations

import queue
import threading

from subtitle_runtime.application.audio_ingress import AudioIngress
from subtitle_runtime.entrypoints.cli import _QueuedAudioSource


class Capture:
    def start(self, on_chunk, *, on_error=None):
        self.push = on_chunk

    def stop(self):
        pass


class ObservedEvent:
    def __init__(self):
        self.event = threading.Event()
        self.waiting = threading.Event()
        self.timeouts = []

    def set(self):
        self.event.set()

    def clear(self):
        self.event.clear()

    def wait(self, timeout=None):
        self.timeouts.append(timeout)
        self.waiting.set()
        return self.event.wait(timeout)


def test_idle_drainer_waits_for_signal_not_periodic_poll():
    capture = Capture()
    source = _QueuedAudioSource(capture, AudioIngress(4))
    event = ObservedEvent()
    source._idle_wait = event
    received = threading.Event()
    values = []

    def consume(chunk):
        values.append(chunk)
        received.set()

    source.start(consume)
    try:
        assert event.waiting.wait(3)
        assert event.timeouts == [None]
        capture.push('audio')
        assert received.wait(3)
        assert values == ['audio']
    finally:
        source.stop()
    assert source._drain_thread is None


def test_enqueue_between_empty_pop_and_wait_is_not_lost():
    empty = threading.Event()
    release = threading.Event()

    class PausedIngress(AudioIngress):
        paused = False

        def pop_nowait(self):
            try:
                return super().pop_nowait()
            except queue.Empty:
                if not self.paused:
                    self.paused = True
                    empty.set()
                    assert release.wait(3)
                raise

    capture = Capture()
    source = _QueuedAudioSource(capture, PausedIngress(4))
    received = threading.Event()
    source.start(lambda _chunk: received.set())
    try:
        assert empty.wait(3)
        capture.push('racing audio')
        release.set()
        assert received.wait(3)
    finally:
        release.set()
        source.stop()


def test_capture_callback_does_not_wait_for_consumer():
    capture = Capture()
    source = _QueuedAudioSource(capture, AudioIngress(4))
    entered = threading.Event()
    release = threading.Event()
    threads = []

    def consume(_chunk):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3)

    source.start(consume)
    try:
        capture.push('audio')
        assert entered.wait(3)
        assert threads == [source._drain_thread.ident]
        assert threads[0] != threading.get_ident()
    finally:
        release.set()
        source.stop()


def test_push_before_clear_remains_visible_in_queue():
    capture = Capture()
    source = _QueuedAudioSource(capture, AudioIngress(4))
    received = threading.Event()

    class InjectBeforeClear(ObservedEvent):
        injected = False

        def clear(self):
            if threading.current_thread() is source._drain_thread and not self.injected:
                self.injected = True
                source._push_chunk('before clear')
            super().clear()

    source._idle_wait = InjectBeforeClear()
    source.start(lambda _chunk: received.set())
    try:
        assert received.wait(3)
    finally:
        source.stop()


def test_coalesced_wakes_preserve_drop_oldest_during_stop():
    capture = Capture()
    source = _QueuedAudioSource(capture, AudioIngress(2))
    entered = threading.Event()
    release = threading.Event()
    values = []

    def consume(chunk):
        values.append(chunk)
        if chunk == 0:
            entered.set()
            assert release.wait(3)

    source.start(consume)
    try:
        capture.push(0)
        assert entered.wait(3)
        for value in range(1, 7):
            capture.push(value)
    finally:
        release.set()
        source.stop()
    assert values == [0, 5, 6]


def test_repeated_idle_start_stop_joins_each_drainer():
    source = _QueuedAudioSource(Capture(), AudioIngress(2))
    threads = []
    for _ in range(20):
        observed = ObservedEvent()
        source._idle_wait = observed
        source.start(lambda _chunk: None)
        threads.append(source._drain_thread)
        assert observed.waiting.wait(3)
        source.stop()
        assert observed.timeouts == [None]
        assert source._drain_thread is None
    assert all(not thread.is_alive() for thread in threads)
