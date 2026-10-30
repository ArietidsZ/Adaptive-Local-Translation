import json
import os
import queue
import statistics
import threading
import time

from subtitle_runtime.application.audio_ingress import AudioIngress
from subtitle_runtime.entrypoints.cli import _QueuedAudioSource


class Capture:
    def start(self, on_chunk, *, on_error=None):
        self.push = on_chunk

    def stop(self):
        pass


class CountedEvent:
    def __init__(self):
        self.event = threading.Event()
        self.count = 0
        self.entered = threading.Event()

    def clear(self):
        self.event.clear()

    def set(self):
        self.event.set()

    def wait(self, timeout=None):
        self.count += 1
        self.entered.set()
        return self.event.wait(timeout)


capture = Capture()
source = _QueuedAudioSource(capture, AudioIngress(200))
event = CountedEvent()
source._idle_wait = event
received = queue.Queue()
source.start(lambda chunk: received.put((chunk, time.perf_counter())))
samples = []
try:
    assert event.entered.wait(3)
    before = event.count
    start = time.perf_counter()
    threading.Event().wait(0.5)
    idle = {
        "wall_s": time.perf_counter() - start,
        "additional_wait_calls": event.count - before,
    }
    for index, phase in enumerate([0, 0.002, 0.006, 0.009] * 25):
        threading.Event().wait(phase)
        start = time.perf_counter()
        capture.push(index)
        item, when = received.get(timeout=3)
        assert item == index
        samples.append(
            {"phase_s": phase, "enqueue_to_callback_ms": (when - start) * 1000}
        )
finally:
    source.stop()
values = sorted(x["enqueue_to_callback_ms"] for x in samples)
print(
    json.dumps(
        {
            "label": os.environ["PROBE_LABEL"],
            "idle": idle,
            "samples": samples,
            "p50_ms": statistics.median(values),
            "p95_ms": values[94],
            "drainer_joined": source._drain_thread is None,
        }
    )
)
