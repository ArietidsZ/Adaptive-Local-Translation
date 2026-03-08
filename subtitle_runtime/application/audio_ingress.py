from __future__ import annotations

import queue

from subtitle_runtime.application.ports import (
    AudioChunk,
    AudioIngressPort,
    IngressReport,
)


class AudioIngress(AudioIngressPort):
    def __init__(self, maxsize: int) -> None:
        self._chunks: queue.Queue[AudioChunk] = queue.Queue(maxsize=maxsize)

    def push(self, chunk: AudioChunk) -> IngressReport:
        dropped_chunks = 0

        if self._chunks.full():
            self._chunks.get_nowait()
            dropped_chunks = 1

        self._chunks.put_nowait(chunk)
        return IngressReport(dropped_chunks=dropped_chunks)

    def pop_nowait(self) -> AudioChunk:
        return self._chunks.get_nowait()
