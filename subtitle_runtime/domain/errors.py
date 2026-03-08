from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureSeverity(StrEnum):
    RECOVERABLE = "recoverable"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class RuntimeFailure:
    kind: str
    message: str
    severity: FailureSeverity

    @property
    def recoverable(self) -> bool:
        return self.severity is FailureSeverity.RECOVERABLE
