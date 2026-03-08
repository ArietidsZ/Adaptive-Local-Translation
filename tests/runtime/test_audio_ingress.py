from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from subtitle_runtime.application.audio_ingress import AudioIngress


def test_audio_ingress_drops_oldest_chunk_when_full() -> None:
    ingress = AudioIngress(maxsize=1)
    first = np.array([1.0], dtype=np.float32)
    second = np.array([2.0], dtype=np.float32)

    ingress.push(first)
    report = ingress.push(second)

    assert report.dropped_chunks == 1
    assert ingress.pop_nowait().tolist() == [2.0]
