"""
OBS Studio 脚本模式 — 直接作为 OBS 插件加载。

使用方法:
  1. OBS → 工具 → 脚本
  2. 添加此脚本 (obs_script.py)
  3. 配置参数（模型、语言、文本源名称）
  4. 点击"启动"

此脚本通过 obspython 直接操作 OBS 文本源，无需 WebSocket 连接。
后台线程处理 音频采集→VAD→ASR→翻译，主线程定时器更新字幕。

注意: OBS 使用内嵌 Python 解释器，需确保 Python 版本与 OBS 匹配。
      需在 OBS 的 Python 设置中配置正确的 Python 路径。
"""

from __future__ import annotations

import sys
import os
import logging

# Make our modules importable — the script dir is added to sys.path.
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import obspython as obs  # type: ignore[import-not-found]

from config import Config
from subtitle_runtime.adapters.obs_script_sink import OBSTextSourceSink
from subtitle_runtime.domain.events import RuntimeState
from subtitle_runtime.entrypoints.obs_plugin import (
    OBSPluginRuntime,
    build_obs_plugin_session,
)

logger = logging.getLogger("obs-subtitle-plugin")

# ── Global state ───────────────────────────────────────────────────

_runtime: OBSPluginRuntime | None = None
_text_sink: OBSTextSourceSink | None = None

# Settings (populated by OBS properties UI)
_settings = {
    "source_name": "subtitle",
    "asr_model": "Qwen/Qwen3-ASR-0.6B",
    "asr_language": "",
    "target_lang": "zh",
    "translation_model": "tencent/HY-MT1.5-1.8B-GPTQ-Int4",
}

_UPDATE_INTERVAL_MS = 100  # poll for new subtitles every 100 ms


# ── OBS script callbacks ──────────────────────────────────────────


def script_description() -> str:
    return (
        "<h2>实时中文字幕</h2>"
        "<p>捕获系统音频 → 语音识别 → 翻译 → 字幕显示</p>"
        "<p>需要 NVIDIA GPU + CUDA</p>"
    )


def script_properties():
    props = obs.obs_properties_create()

    obs.obs_properties_add_text(
        props, "source_name", "字幕文本源名称", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(
        props,
        "asr_model",
        "ASR 模型 (例如 Qwen/Qwen3-ASR-0.6B)",
        obs.OBS_TEXT_DEFAULT,
    )
    obs.obs_properties_add_text(
        props, "asr_language", "源语言 (留空=自动检测)", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_text(props, "target_lang", "目标语言", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(
        props, "translation_model", "翻译模型", obs.OBS_TEXT_DEFAULT
    )

    obs.obs_properties_add_button(props, "btn_start", "▶ 启动", _on_start_clicked)
    obs.obs_properties_add_button(props, "btn_stop", "■ 停止", _on_stop_clicked)

    return props


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, "source_name", "subtitle")
    obs.obs_data_set_default_string(settings, "asr_model", "Qwen/Qwen3-ASR-0.6B")
    obs.obs_data_set_default_string(settings, "asr_language", "")
    obs.obs_data_set_default_string(settings, "target_lang", "zh")
    obs.obs_data_set_default_string(
        settings, "translation_model", "tencent/HY-MT1.5-1.8B-GPTQ-Int4"
    )


def script_update(settings):
    _settings["source_name"] = obs.obs_data_get_string(settings, "source_name")
    _settings["asr_model"] = obs.obs_data_get_string(settings, "asr_model")
    _settings["asr_language"] = obs.obs_data_get_string(settings, "asr_language")
    _settings["target_lang"] = obs.obs_data_get_string(settings, "target_lang")
    _settings["translation_model"] = obs.obs_data_get_string(
        settings, "translation_model"
    )


def script_unload():
    _stop_pipeline()


# ── Button handlers ────────────────────────────────────────────────


def _on_start_clicked(props, prop):
    global _runtime, _text_sink
    if _runtime is not None:
        return True  # already running

    cfg = Config(
        asr_model=_settings["asr_model"],
        asr_language=_settings["asr_language"] or None,
        translation_model=_settings["translation_model"],
        translation_target_lang=_settings["target_lang"],
        obs_source_name=_settings["source_name"],
    )

    _runtime = build_obs_plugin_session(cfg)
    _text_sink = OBSTextSourceSink(obs, _settings["source_name"])
    _runtime.session.start()

    if _runtime.session.status.state is RuntimeState.FAILED:
        logger.error("Pipeline failed to start")
        _stop_pipeline()
        return True

    obs.timer_add(_timer_tick, _UPDATE_INTERVAL_MS)
    logger.info("Pipeline started")
    return True


def _on_stop_clicked(props, prop):
    _stop_pipeline()
    return True


def _stop_pipeline():
    global _runtime, _text_sink
    was_running = _runtime is not None or _text_sink is not None
    obs.timer_remove(_timer_tick)
    first_error = None

    if _runtime is not None:
        try:
            _runtime.session.stop()
        except Exception as error:
            first_error = error

        try:
            _runtime.result_sink.clear()
        except Exception as error:
            if first_error is None:
                first_error = error

        _runtime = None

    if _text_sink is not None:
        try:
            _text_sink.clear()
        except Exception as error:
            if first_error is None:
                first_error = error

        _text_sink = None

    if was_running:
        logger.info("Pipeline stopped")

    if first_error is not None:
        raise first_error


# ── Timer tick (main OBS thread) ───────────────────────────────────


def _timer_tick():
    if _runtime is None or _text_sink is None:
        return

    status = _runtime.status_sink.poll_latest()
    if status is not None and status.state is RuntimeState.FAILED:
        _stop_pipeline()
        return

    text = _runtime.result_sink.poll_latest()
    if text is not None:
        _text_sink.update(text)
