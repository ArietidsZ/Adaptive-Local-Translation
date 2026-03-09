from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from subtitle_runtime.domain import FailureSeverity, RuntimeFailure


def test_runtime_failure_marks_recoverable_severity() -> None:
    failure = RuntimeFailure(
        kind="delivery",
        message="OBS retry later",
        severity=FailureSeverity.RECOVERABLE,
    )

    assert failure.kind == "delivery"
    assert failure.severity is FailureSeverity.RECOVERABLE
    assert failure.recoverable is True


def test_runtime_failure_marks_terminal_severity_as_not_recoverable() -> None:
    failure = RuntimeFailure(
        kind="adapter",
        message="OBS authentication failed",
        severity=FailureSeverity.TERMINAL,
    )

    assert failure.severity is FailureSeverity.TERMINAL
    assert failure.recoverable is False
