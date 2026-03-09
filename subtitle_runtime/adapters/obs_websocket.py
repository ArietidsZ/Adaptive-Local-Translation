from __future__ import annotations

from typing import Any, Protocol

from subtitle_runtime.domain.events import SubtitleEvent


class OBSSubtitleFactory(Protocol):
    def __call__(self, cfg: Any) -> Any: ...


def _default_factory(cfg: Any) -> Any:
    from obs import OBSSubtitle

    return OBSSubtitle(cfg)


class OBSWebSocketSubtitleAdapter:
    def __init__(
        self,
        cfg: Any,
        factory: OBSSubtitleFactory = _default_factory,
    ) -> None:
        self._obs = factory(cfg)

    def publish(self, event: SubtitleEvent) -> None:
        self._obs.update(event.translated_text)

    def clear(self) -> None:
        self._obs.clear()

    def close(self) -> None:
        self._obs.close()
