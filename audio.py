"""
WASAPI loopback audio capture for Windows.

Captures system audio output (what the speakers play) using PyAudioWPatch
and feeds 16 kHz mono float32 chunks into a queue for downstream processing.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)


class AudioCapture:
    """Continuously captures system audio via WASAPI loopback."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._running = False
        self._thread: threading.Thread | None = None

    # ── public API ─────────────────────────────────────────────────

    def start(
        self,
        callback: Callable[[np.ndarray], None],
        *,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Start capturing.  *callback* receives (N,) float32 arrays at 16 kHz."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            args=(callback, on_error),
            daemon=True,
            name="audio-capture",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ── internals ──────────────────────────────────────────────────

    def _capture_loop(
        self,
        callback: Callable[[np.ndarray], None],
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        import pyaudiowpatch as pyaudio  # Windows-only; imported here to fail fast

        pa = pyaudio.PyAudio()
        try:
            wasapi_info = _find_wasapi_host(pa)
            loopback = _find_loopback_device(pa, wasapi_info)
            logger.info(
                "Capturing from: %s  (channels=%d, rate=%d)",
                loopback["name"],
                loopback["maxInputChannels"],
                int(loopback["defaultSampleRate"]),
            )

            device_rate = int(loopback["defaultSampleRate"])
            device_channels = loopback["maxInputChannels"]
            chunk_samples = int(device_rate * self._cfg.chunk_duration_s)

            stream = pa.open(
                format=pyaudio.paFloat32,
                channels=device_channels,
                rate=device_rate,
                input=True,
                input_device_index=loopback["index"],
                frames_per_buffer=chunk_samples,
            )

            while self._running:
                data = stream.read(chunk_samples, exception_on_overflow=False)
                pcm = np.frombuffer(data, dtype=np.float32)

                # Down-mix to mono if stereo.
                if device_channels > 1:
                    pcm = pcm.reshape(-1, device_channels).mean(axis=1)

                # Resample to 16 kHz if needed.
                if device_rate != self._cfg.sample_rate:
                    pcm = _resample(pcm, device_rate, self._cfg.sample_rate)

                callback(pcm)

            stream.stop_stream()
            stream.close()
        except Exception as error:
            logger.exception("Audio capture failed")
            if on_error is not None:
                on_error(error)
        finally:
            self._running = False
            pa.terminate()


# ── helpers ────────────────────────────────────────────────────────


def _find_wasapi_host(pa) -> dict:
    for i in range(pa.get_host_api_count()):
        info = pa.get_host_api_info_by_index(i)
        if info["name"].lower().startswith("windows wasapi"):
            return info
    raise RuntimeError("WASAPI host API not found — this only works on Windows")


def _find_loopback_device(pa, wasapi_info: dict) -> dict:
    default_output_idx = wasapi_info["defaultOutputDevice"]
    default_output = pa.get_device_info_by_index(default_output_idx)
    default_name = default_output["name"]

    # Loopback devices are listed with "[Loopback]" in the name.
    for i in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(i)
        if dev.get("isLoopbackDevice", False):
            if default_name in dev["name"]:
                return dev

    # Fallback: any loopback device.
    for i in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(i)
        if dev.get("isLoopbackDevice", False):
            logger.warning("Using fallback loopback device: %s", dev["name"])
            return dev

    raise RuntimeError("No WASAPI loopback device found")


def _resample(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear-interpolation resample.  Good enough for speech."""
    if src_rate == dst_rate:
        return pcm
    ratio = dst_rate / src_rate
    n_out = int(len(pcm) * ratio)
    indices = np.linspace(0, len(pcm) - 1, n_out)
    return np.interp(indices, np.arange(len(pcm)), pcm).astype(np.float32)
