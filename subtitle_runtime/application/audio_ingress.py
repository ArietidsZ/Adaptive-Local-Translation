from __future__ import annotations

import queue
import threading

from subtitle_runtime.application.ports import (
    AudioChunk,
    AudioIngressPort,
    IngressReport,
)


class AudioIngress(AudioIngressPort):
    def __init__(self, maxsize: int) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")

        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._chunks: queue.Queue[AudioChunk] = queue.Queue(maxsize=maxsize)

    def push(self, chunk: AudioChunk) -> IngressReport:
        with self._lock:
            dropped_chunks = 0

            if self._chunks.qsize() >= self._maxsize:
                self._chunks.get_nowait()
                dropped_chunks = 1

            self._chunks.put_nowait(chunk)
            return IngressReport(dropped_chunks=dropped_chunks)

    def pop_nowait(self) -> AudioChunk:
        with self._lock:
            return self._chunks.get_nowait()
