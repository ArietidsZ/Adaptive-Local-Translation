from __future__ import annotations

import signal
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config
from subtitle_runtime.domain.events import RuntimeState
from subtitle_runtime.entrypoints import cli as cli_module
from subtitle_runtime.entrypoints.cli import build_cli_session


class FakeSink:
    def __init__(self):
        self.values = []
        self.cleared = 0
        self.closed = 0

    def publish(self, value):
        self.values.append(value)

    def clear(self) -> None:
        self.cleared += 1

    def close(self) -> None:
        self.closed += 1


def test_build_cli_session_returns_session_controller() -> None:
    session = build_cli_session(
        Config(),
        subtitle_sink=FakeSink(),
        status_sink=FakeSink(),
    )

    assert session.__class__.__name__ == "SessionController"


def test_run_cli_exits_without_sleep_when_startup_fails(monkeypatch) -> None:
    class FailingAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def start(self, on_chunk) -> None:
            del on_chunk
            raise RuntimeError("boom")

        def stop(self) -> None:
            raise AssertionError("stop should not be called after failed startup")

    sink = FakeSink()

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FailingAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "OBSWebSocketSubtitleAdapter", lambda cfg: sink)
    monkeypatch.setattr(
        cli_module.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(
            AssertionError("run_cli slept after failure")
        ),
    )

    session = cli_module.run_cli(Config())

    assert session.status.state is RuntimeState.FAILED


def test_run_cli_processes_audio_after_capture_callback_returns(monkeypatch) -> None:
    call_order = []
    sink = FakeSink()

    class FakeAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg
            self.stopped = 0

        def start(self, on_chunk) -> None:
            call_order.append("start")
            on_chunk(np.array([0.25], dtype=np.float32))
            call_order.append("after-callback")

        def stop(self) -> None:
            call_order.append("stop")
            self.stopped += 1

    class FakeVADAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def process_chunk(self, chunk, on_speech) -> None:
            call_order.append("segmenter")
            on_speech(chunk)

        def flush(self, on_speech) -> None:
            del on_speech
            call_order.append("flush")

    class FakeASRAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def transcribe(self, segment) -> str:
            del segment
            call_order.append("asr")
            return "hello"

    class FakeTranslatorAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def translate(self, text, source_lang="", target_lang=None) -> str:
            del source_lang, target_lang
            call_order.append(f"translate:{text}")
            return "ni hao"

    def interrupt_sleep(seconds: float) -> None:
        del seconds
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FakeAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "VADAdapter", FakeVADAdapter)
    monkeypatch.setattr(cli_module, "ASRAdapter", FakeASRAdapter)
    monkeypatch.setattr(cli_module, "TranslatorAdapter", FakeTranslatorAdapter)
    monkeypatch.setattr(cli_module, "OBSWebSocketSubtitleAdapter", lambda cfg: sink)
    monkeypatch.setattr(cli_module.time, "sleep", interrupt_sleep)

    cli_module.run_cli(Config())

    assert call_order.index("after-callback") < call_order.index("segmenter")
    assert sink.values[-1].translated_text == "ni hao"
    assert sink.cleared == 1
    assert sink.closed == 1


def test_run_cli_registers_sigterm_handler_and_shuts_down(monkeypatch) -> None:
    handlers = {}
    sink = FakeSink()

    class FakeAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def start(self, on_chunk) -> None:
            del on_chunk

        def stop(self) -> None:
            sink.values.append("stopped")

    class FakeVADAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def process_chunk(self, chunk, on_speech) -> None:
            del chunk, on_speech

        def flush(self, on_speech) -> None:
            del on_speech
            sink.values.append("flushed")

    def fake_signal(sig, handler):
        handlers[sig] = handler

    def fire_sigterm(seconds: float) -> None:
        del seconds
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FakeAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "VADAdapter", FakeVADAdapter)
    monkeypatch.setattr(cli_module, "OBSWebSocketSubtitleAdapter", lambda cfg: sink)
    monkeypatch.setattr(cli_module.signal, "signal", fake_signal)
    monkeypatch.setattr(cli_module.time, "sleep", fire_sigterm)

    cli_module.run_cli(Config())

    assert signal.SIGINT in handlers
    assert signal.SIGTERM in handlers
    assert sink.values == ["stopped"]
    assert sink.cleared == 1
    assert sink.closed == 1
