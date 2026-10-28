"""
Voice Activity Detection using Silero VAD.

Accepts arbitrary chunk sizes from upstream and internally re-frames audio
to Silero's required fixed window size.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

_SILERO_SAMPLE_RATE = 16_000  # Silero VAD requires 16 kHz input
_SILERO_FRAME_SAMPLES = 512  # Silero VAD expects exactly 512 samples at 16 kHz


class VAD:
    """Streaming VAD: feed chunks, get speech segment callbacks."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        if cfg.offline_only or cfg.vad_model_path:
            model_path = (
                Path(cfg.vad_model_path).expanduser() if cfg.vad_model_path else
                Path(torch.hub.get_dir()) / "snakers4_silero-vad_master" /
                "src" / "silero_vad" / "data" / "silero_vad.jit"
            )
            if not model_path.is_file():
                raise FileNotFoundError(
                    "Local Silero VAD model missing; set vad_model_path to a "
                    "trusted silero_vad.jit file before offline startup"
                )
            self._model = torch.jit.load(str(model_path), map_location="cpu")
        else:
            self._model, _ = torch.hub.load(
                "snakers4/silero-vad", "silero_vad", trust_repo=True
            )
        self._model.eval()

        self._frame_samples = _SILERO_FRAME_SAMPLES
        self._frame_seconds = self._frame_samples / _SILERO_SAMPLE_RATE
        self._padding_frames = max(
            1,
            int(round(self._cfg.vad_padding_s / self._frame_seconds)),
        )

        self._leftover = np.empty(0, dtype=np.float32)
        self._pre_speech: deque[np.ndarray] = deque(maxlen=self._padding_frames)
        self._trailing_silence: list[np.ndarray] = []

        self._speech_buf: list[np.ndarray] = []
        self._is_speaking = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0

    def process_chunk(
        self,
        chunk: np.ndarray,
        on_speech: Callable[[np.ndarray], None],
    ) -> None:
        """Feed a 16 kHz chunk (any length) and emit speech segments."""
        if chunk.size == 0:
            return

        chunk_f32 = chunk.astype(np.float32, copy=False)
        if self._leftover.size:
            chunk_f32 = np.concatenate((self._leftover, chunk_f32))

        full = (len(chunk_f32) // self._frame_samples) * self._frame_samples
        if full == 0:
            self._leftover = chunk_f32
            return

        framed = chunk_f32[:full].reshape(-1, self._frame_samples)
        for frame in framed:
            self._process_frame(frame, on_speech)

        self._leftover = chunk_f32[full:]

    def flush(self, on_speech: Callable[[np.ndarray], None]) -> None:
        """Emit any remaining buffered speech."""
        if self._leftover.size:
            padded = np.pad(
                self._leftover,
                (0, self._frame_samples - len(self._leftover)),
            ).astype(np.float32, copy=False)
            self._process_frame(padded, on_speech)
            self._leftover = np.empty(0, dtype=np.float32)

        if self._is_speaking and self._trailing_silence:
            self._speech_buf.extend(self._trailing_silence)
            self._speech_duration += len(self._trailing_silence) * self._frame_seconds
            self._trailing_silence.clear()

        if self._is_speaking and self._speech_buf:
            self._emit(on_speech)

        self._pre_speech.clear()

    def _process_frame(
        self,
        frame: np.ndarray,
        on_speech: Callable[[np.ndarray], None],
    ) -> None:
        with torch.no_grad():
            prob = self._model(torch.from_numpy(frame), _SILERO_SAMPLE_RATE).item()

        if prob >= self._cfg.vad_threshold:
            if not self._is_speaking:
                self._is_speaking = True
                self._speech_duration = 0.0
                self._silence_duration = 0.0
                self._speech_buf.clear()

                if self._pre_speech:
                    self._speech_buf.extend(self._pre_speech)
                    self._speech_duration += len(self._pre_speech) * self._frame_seconds
                    self._pre_speech.clear()

            if self._trailing_silence:
                self._speech_buf.extend(self._trailing_silence)
                self._speech_duration += (
                    len(self._trailing_silence) * self._frame_seconds
                )
                self._trailing_silence.clear()
                self._silence_duration = 0.0

            self._speech_buf.append(frame.copy())
            self._speech_duration += self._frame_seconds

            if self._speech_duration >= self._cfg.vad_max_speech_s:
                self._emit(on_speech)
            return

        if self._is_speaking:
            self._trailing_silence.append(frame.copy())
            self._silence_duration += self._frame_seconds

            if self._silence_duration >= self._cfg.vad_padding_s:
                self._speech_buf.extend(self._trailing_silence)
                self._speech_duration += (
                    len(self._trailing_silence) * self._frame_seconds
                )
                self._trailing_silence.clear()
                self._silence_duration = 0.0
                self._emit(on_speech)
            return

        self._pre_speech.append(frame.copy())

    def _emit(self, on_speech: Callable[[np.ndarray], None]) -> None:
        if self._speech_duration < self._cfg.vad_min_speech_s:
            logger.debug("Dropping short segment (%.2f s)", self._speech_duration)
        else:
            segment = np.concatenate(self._speech_buf)
            logger.debug("Speech segment: %.2f s", len(segment) / _SILERO_SAMPLE_RATE)
            on_speech(segment)

        self._trailing_silence.clear()
        self._speech_buf.clear()
        self._is_speaking = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0
