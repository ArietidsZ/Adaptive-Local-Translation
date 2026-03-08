#!/usr/bin/env python3
"""
OBS 实时中文字幕 — 入口

Usage:
    python main.py [OPTIONS]

All options default to sensible values — just ``python main.py`` is enough
if OBS WebSocket is running on localhost with default port.
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import Config
from subtitle_runtime.entrypoints.cli import run_cli


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-time Chinese subtitles for OBS")

    # ASR
    parser.add_argument(
        "--asr-model",
        default="Qwen/Qwen3-ASR-0.6B",
        help="Qwen3-ASR model name (default: Qwen/Qwen3-ASR-0.6B)",
    )
    parser.add_argument(
        "--asr-language",
        default=None,
        help="Source language (e.g. en/ja/zh or English/Japanese/Chinese)",
    )

    # Translation
    parser.add_argument(
        "--target-lang",
        default="zh",
        help="Target language code (default: zh)",
    )
    parser.add_argument(
        "--translation-model",
        default="tencent/HY-MT1.5-1.8B-GPTQ-Int4",
        help="HuggingFace translation model",
    )

    # OBS
    parser.add_argument("--obs-host", default="localhost")
    parser.add_argument("--obs-port", type=int, default=4455)
    parser.add_argument("--obs-password", default="")
    parser.add_argument(
        "--obs-source",
        default="subtitle",
        help="OBS Text (GDI+) source name (default: subtitle)",
    )

    # Misc
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
        stream=sys.stderr,
    )

    cfg = Config(
        asr_model=args.asr_model,
        asr_language=args.asr_language,
        translation_model=args.translation_model,
        translation_target_lang=args.target_lang,
        obs_host=args.obs_host,
        obs_port=args.obs_port,
        obs_password=args.obs_password,
        obs_source_name=args.obs_source,
    )

    run_cli(cfg)


if __name__ == "__main__":
    main()
