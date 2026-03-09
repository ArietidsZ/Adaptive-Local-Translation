from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_legacy_engine_import_path_still_resolves() -> None:
    from engine import RuntimeState  # noqa: F401
