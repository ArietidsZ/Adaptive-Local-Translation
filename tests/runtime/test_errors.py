from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from subtitle_runtime.domain.errors import FailureSeverity, RuntimeFailure


def test_runtime_failure_marks_recoverable_severity() -> None:
    failure = RuntimeFailure(
        kind="delivery",
        message="OBS retry later",
        severity=FailureSeverity.RECOVERABLE,
        recoverable=True,
    )

    assert failure.kind == "delivery"
    assert failure.recoverable is True
