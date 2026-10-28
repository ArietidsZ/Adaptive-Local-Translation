"""
Global configuration for the OBS real-time Chinese subtitle pipeline.
All tunables live here — no magic constants scattered across modules.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Config:
    # Model loading policy (shared by dashboard and loaders).
    model_cache_dir: str | None = None
    vad_model_path: str | None = None  # trusted local Silero TorchScript file
    offline_only: bool = False
    translation_trust_remote_code: bool = False

    # ── Audio capture ──────────────────────────────────────────────
    audio_device_index: int | None = None  # None = auto-detect default output
    sample_rate: int = 16_000  # internal processing rate
    chunk_duration_s: float = 0.5  # seconds per audio chunk fed to VAD

    # ── VAD ────────────────────────────────────────────────────────
    vad_threshold: float = 0.45  # Silero speech probability threshold
    vad_min_speech_s: float = 0.5  # drop segments shorter than this
    vad_max_speech_s: float = 30.0  # force-split segments longer than this
    vad_padding_s: float = 0.3  # pad speech segments on both sides

    # ── ASR (Qwen3-ASR) ────────────────────────────────────────────
    asr_model: str = "Qwen/Qwen3-ASR-0.6B"
    asr_device: str = "cuda:0"
    asr_compute_type: str = "float16"  # float16 / bfloat16 / float32
    asr_max_new_tokens: int = 512
    asr_language: str | None = None  # None = auto-detect source language

    # ── Translation (HY-MT1.5) ─────────────────────────────────────
    translation_model: str = "tencent/HY-MT1.5-1.8B-GPTQ-Int4"
    translation_device: str = "cuda"
    translation_target_lang: str = "zh"
    translation_max_new_tokens: int = 512
    translation_top_k: int = 20
    translation_top_p: float = 0.6
    translation_temperature: float = 0.7
    translation_repetition_penalty: float = 1.05

    # ── OBS WebSocket ──────────────────────────────────────────────
    obs_host: str = "localhost"
    obs_port: int = 4455
    obs_password: str = ""
    obs_source_name: str = "subtitle"  # Text (GDI+) source name in OBS
