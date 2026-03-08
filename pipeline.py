"""Legacy CLI wrapper for the runtime session entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_runtime.entrypoints.cli import run_cli

if TYPE_CHECKING:
    from config import Config


class Pipeline:
    """Compatibility wrapper around the new runtime session core."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def run(self) -> None:
        run_cli(self._cfg)
