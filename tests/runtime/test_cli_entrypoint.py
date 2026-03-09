from __future__ import annotations

import signal
import sys
import threading
import time
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


def test_build_cli_session_starts_operational_audio_processing(monkeypatch) -> None:
    call_order = []
    sink = FakeSink()

    class FakeAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def start(self, on_chunk) -> None:
            call_order.append("start")
            on_chunk(np.array([0.25], dtype=np.float32))
            call_order.append("after-callback")

        def stop(self) -> None:
            call_order.append("stop")

    class FakeVADAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def process_chunk(self, chunk, on_speech) -> None:
            call_order.append("segmenter")
            on_speech(chunk)

        def flush(self, on_speech) -> None:
            del on_speech

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

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FakeAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "VADAdapter", FakeVADAdapter)
    monkeypatch.setattr(cli_module, "ASRAdapter", FakeASRAdapter)
    monkeypatch.setattr(cli_module, "TranslatorAdapter", FakeTranslatorAdapter)

    session = build_cli_session(
        Config(),
        subtitle_sink=sink,
        status_sink=FakeSink(),
    )

    session.start()
    session.stop()

    assert call_order.index("after-callback") < call_order.index("segmenter")
    assert sink.values[-1].translated_text == "ni hao"


def test_build_cli_session_stop_drains_buffered_audio(monkeypatch) -> None:
    call_order = []
    sink = FakeSink()

    class FakeAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg
            self._on_chunk = None

        def start(self, on_chunk) -> None:
            self._on_chunk = on_chunk

        def stop(self) -> None:
            call_order.append("stop")
            self._on_chunk(np.array([0.25], dtype=np.float32))
            call_order.append("after-stop-chunk")

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

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FakeAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "VADAdapter", FakeVADAdapter)
    monkeypatch.setattr(cli_module, "ASRAdapter", FakeASRAdapter)
    monkeypatch.setattr(cli_module, "TranslatorAdapter", FakeTranslatorAdapter)

    session = build_cli_session(
        Config(),
        subtitle_sink=sink,
        status_sink=FakeSink(),
    )

    session.start()
    session.stop()

    assert call_order.index("stop") < call_order.index("segmenter")
    assert call_order.index("after-stop-chunk") < call_order.index("segmenter")
    assert call_order.index("segmenter") < call_order.index("flush")
    assert sink.values[-1].translated_text == "ni hao"


def test_build_cli_session_stop_waits_for_inflight_processing(monkeypatch) -> None:
    call_order = []
    sink = FakeSink()
    allow_processing = threading.Event()

    class FakeAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def start(self, on_chunk) -> None:
            on_chunk(np.array([0.25], dtype=np.float32))

        def stop(self) -> None:
            call_order.append("stop")

    class FakeVADAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def process_chunk(self, chunk, on_speech) -> None:
            call_order.append("segmenter-start")
            allow_processing.wait()
            call_order.append("segmenter-finish")
            on_speech(chunk)

        def flush(self, on_speech) -> None:
            del on_speech
            call_order.append("flush")

    class FakeASRAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def transcribe(self, segment) -> str:
            del segment
            return "hello"

    class FakeTranslatorAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def translate(self, text, source_lang="", target_lang=None) -> str:
            del source_lang, target_lang
            return text

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FakeAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "VADAdapter", FakeVADAdapter)
    monkeypatch.setattr(cli_module, "ASRAdapter", FakeASRAdapter)
    monkeypatch.setattr(cli_module, "TranslatorAdapter", FakeTranslatorAdapter)

    session = build_cli_session(
        Config(),
        subtitle_sink=sink,
        status_sink=FakeSink(),
    )

    session.start()

    stop_thread = threading.Thread(target=session.stop)
    stop_thread.start()
    time.sleep(1.05)

    assert "flush" not in call_order
    assert stop_thread.is_alive()

    allow_processing.set()
    stop_thread.join(timeout=1.0)

    assert not stop_thread.is_alive()
    assert call_order.index("segmenter-finish") < call_order.index("flush")


def test_run_cli_exits_without_sleep_when_startup_fails(monkeypatch) -> None:
    class FailingAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def start(self, on_chunk) -> None:
            del on_chunk
            raise RuntimeError("boom")

        def stop(self) -> None:
            sink.values.append("stopped")

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
    assert sink.values == ["stopped"]
    assert sink.cleared == 1
    assert sink.closed == 1


def test_run_cli_cleans_up_after_async_startup_failure(monkeypatch) -> None:
    call_order = []
    sink = FakeSink()

    class FailingAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def start(self, on_chunk, *, on_error=None) -> None:
            del on_chunk
            call_order.append("start")
            on_error(RuntimeError("boom"))
            call_order.append("after-error")

        def stop(self) -> None:
            call_order.append("stop")

    class FakeVADAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def process_chunk(self, chunk, on_speech) -> None:
            del chunk, on_speech

        def flush(self, on_speech) -> None:
            del on_speech
            call_order.append("flush")

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FailingAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "VADAdapter", FakeVADAdapter)
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
    assert call_order == ["start", "after-error", "stop"]
    assert sink.cleared == 1
    assert sink.closed == 1


def test_run_cli_drains_buffered_audio_during_shutdown(monkeypatch) -> None:
    call_order = []
    sink = FakeSink()

    class FakeAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg
            self._on_chunk = None

        def start(self, on_chunk) -> None:
            call_order.append("start")
            self._on_chunk = on_chunk

        def stop(self) -> None:
            call_order.append("stop")
            self._on_chunk(np.array([0.25], dtype=np.float32))
            call_order.append("after-stop-chunk")

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

    assert call_order.index("stop") < call_order.index("segmenter")
    assert call_order.index("after-stop-chunk") < call_order.index("segmenter")
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


def test_run_cli_stops_after_post_start_async_failure(monkeypatch) -> None:
    sink = FakeSink()
    audio_source = None
    sleep_calls = []

    class FakeAudioCaptureAdapter:
        def __init__(self, cfg) -> None:
            del cfg
            nonlocal audio_source
            audio_source = self
            self.on_error = None

        def start(self, on_chunk, *, on_error=None) -> None:
            del on_chunk
            self.on_error = on_error

        def stop(self) -> None:
            sink.values.append("stopped")

    class FakeVADAdapter:
        def __init__(self, cfg) -> None:
            del cfg

        def process_chunk(self, chunk, on_speech) -> None:
            del chunk, on_speech

        def flush(self, on_speech) -> None:
            del on_speech

    def fail_after_async_error(seconds: float) -> None:
        del seconds
        sleep_calls.append("sleep")
        audio_source.on_error(RuntimeError("boom"))

        if len(sleep_calls) > 1:
            raise AssertionError("run_cli kept sleeping after async failure")

    monkeypatch.setattr(cli_module, "AudioCaptureAdapter", FakeAudioCaptureAdapter)
    monkeypatch.setattr(cli_module, "VADAdapter", FakeVADAdapter)
    monkeypatch.setattr(cli_module, "OBSWebSocketSubtitleAdapter", lambda cfg: sink)
    monkeypatch.setattr(cli_module.time, "sleep", fail_after_async_error)

    session = cli_module.run_cli(Config())

    assert session.status.state is RuntimeState.FAILED
    assert sleep_calls == ["sleep"]
    assert sink.values == ["stopped"]
    assert sink.cleared == 1
    assert sink.closed == 1
