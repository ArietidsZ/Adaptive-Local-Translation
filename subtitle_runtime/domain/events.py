from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RuntimeState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class RuntimeStatus:
    state: RuntimeState

    @property
    def healthy(self) -> bool:
        return self.state in {RuntimeState.STARTING, RuntimeState.RUNNING}


@dataclass(frozen=True)
class SubtitleEvent:
    source_text: str
    source_language: str
    translated_text: str
    latency_ms: float
