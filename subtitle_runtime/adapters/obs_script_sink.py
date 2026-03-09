from __future__ import annotations

from typing import Any


class OBSTextSourceSink:
    def __init__(self, obs_module: Any, source_name: str) -> None:
        self._obs = obs_module
        self._source_name = source_name

    def update(self, text: str) -> None:
        source = self._obs.obs_get_source_by_name(self._source_name)
        if source is None:
            return

        settings = self._obs.obs_data_create()
        self._obs.obs_data_set_string(settings, "text", text)
        self._obs.obs_source_update(source, settings)
        self._obs.obs_data_release(settings)
        self._obs.obs_source_release(source)

    def clear(self) -> None:
        self.update("")
