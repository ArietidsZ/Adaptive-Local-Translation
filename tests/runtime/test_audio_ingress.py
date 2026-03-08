from __future__ import annotations

import queue
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from subtitle_runtime.application.audio_ingress import AudioIngress


class _ConcurrentDrainQueue:
    def __init__(self) -> None:
        self.items: list[np.ndarray] = []

    def qsize(self) -> int:
        return 0

    def get_nowait(self) -> np.ndarray:
        if self.items:
            return self.items.pop(0)
        raise queue.Empty

    def put_nowait(self, chunk: np.ndarray) -> None:
        self.items.append(chunk)


def test_audio_ingress_drops_oldest_chunk_when_full() -> None:
    ingress = AudioIngress(maxsize=1)
    first = np.array([1.0], dtype=np.float32)
    second = np.array([2.0], dtype=np.float32)

    ingress.push(first)
    report = ingress.push(second)

    assert report.dropped_chunks == 1
    assert ingress.pop_nowait().tolist() == [2.0]


def test_audio_ingress_reports_zero_drops_when_not_full() -> None:
    ingress = AudioIngress(maxsize=2)

    report = ingress.push(np.array([1.0], dtype=np.float32))

    assert report.dropped_chunks == 0
    assert ingress.pop_nowait().tolist() == [1.0]


def test_audio_ingress_push_handles_consumer_draining_race() -> None:
    ingress = AudioIngress(maxsize=1)
    racey_queue = _ConcurrentDrainQueue()
    ingress._chunks = racey_queue  # type: ignore[assignment]

    report = ingress.push(np.array([2.0], dtype=np.float32))

    assert report.dropped_chunks == 0
    assert racey_queue.items[0].tolist() == [2.0]


def test_audio_ingress_rejects_non_positive_maxsize() -> None:
    with pytest.raises(ValueError, match="maxsize must be positive"):
        AudioIngress(maxsize=0)
