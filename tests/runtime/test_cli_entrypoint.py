from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config
from subtitle_runtime.entrypoints.cli import build_cli_session


class FakeSink:
    def __init__(self):
        self.values = []

    def publish(self, value):
        self.values.append(value)


def test_build_cli_session_returns_session_controller() -> None:
    session = build_cli_session(
        Config(),
        subtitle_sink=FakeSink(),
        status_sink=FakeSink(),
    )

    assert session.__class__.__name__ == "SessionController"
