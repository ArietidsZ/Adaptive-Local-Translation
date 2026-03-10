from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

pytest_plugins = ("aiohttp.pytest_plugin",)

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import web_server
from subtitle_runtime.domain.events import RuntimeState, RuntimeStatus, SubtitleEvent
from web_server import RuntimeStatusSink, RuntimeSubtitleSink, WebDashboard


def run_frontend_scenario(script: str) -> dict:
    app_source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    node_script = textwrap.dedent(
        f"""
        const vm = require('node:vm');

        class FakeClassList {{
          constructor() {{
            this._classes = new Set();
          }}

          add(...names) {{
            for (const name of names) this._classes.add(name);
          }}

          remove(...names) {{
            for (const name of names) this._classes.delete(name);
          }}

          contains(name) {{
            return this._classes.has(name);
          }}
        }}

        class FakeElement {{
          constructor(id = '') {{
            this.id = id;
            this.textContent = '';
            this.value = '';
            this.checked = false;
            this.disabled = false;
            this.className = '';
            this.style = {{}};
            this.attributes = {{}};
            this.listeners = {{}};
            this.children = [];
            this.classList = new FakeClassList();
            this.innerHTML = '';
          }}

          setAttribute(name, value) {{
            this.attributes[name] = String(value);
          }}

          getAttribute(name) {{
            return this.attributes[name] ?? null;
          }}

          addEventListener(type, handler) {{
            this.listeners[type] = handler;
          }}

          dispatchEvent(event) {{
            const enriched = {{
              preventDefault() {{}},
              ...event,
              target: event.target ?? this,
              currentTarget: this,
            }};
            const handler = this.listeners[enriched.type];
            if (handler) handler(enriched);
          }}

          appendChild(child) {{
            this.children.push(child);
            return child;
          }}

          querySelectorAll(selector) {{
            if (selector === '.subtitle-entry') {{
              return this.children.filter((child) => child.className === 'subtitle-entry');
            }}
            return [];
          }}

          querySelector(selector) {{
            return this.querySelectorAll(selector)[0] ?? null;
          }}

          scrollTo() {{}}

          remove() {{
            this.removed = true;
          }}
        }}

        class FakeWebSocket {{
          constructor(url) {{
            this.url = url;
            this.readyState = FakeWebSocket.initialReadyState;
            this.sent = [];
            FakeWebSocket.instance = this;
          }}

          send(payload) {{
            this.sent.push(JSON.parse(payload));
          }}

          close() {{
            this.readyState = FakeWebSocket.CLOSED;
            if (this.onclose) this.onclose();
          }}
        }}

        FakeWebSocket.CONNECTING = 0;
        FakeWebSocket.OPEN = 1;
        FakeWebSocket.CLOSED = 3;
        FakeWebSocket.initialReadyState = FakeWebSocket.CONNECTING;
        FakeWebSocket.instance = null;

        const elements = {{
          '#connectionDot': new FakeElement('connectionDot'),
          '#statusIcon': new FakeElement('statusIcon'),
          '#statusEmoji': new FakeElement('statusEmoji'),
          '#statusLabel': new FakeElement('statusLabel'),
          '#statusPill': new FakeElement('statusPill'),
          '#statusPillText': new FakeElement('statusPillText'),
          '#statusDetail': new FakeElement('statusDetail'),
          '#btnStart': new FakeElement('btnStart'),
          '#btnStop': new FakeElement('btnStop'),
          '#btnSettings': new FakeElement('btnSettings'),
          '#btnClear': new FakeElement('btnClear'),
          '#btnSaveSettings': new FakeElement('btnSaveSettings'),
          '#feedList': new FakeElement('feedList'),
          '#feedEmpty': new FakeElement('feedEmpty'),
          '#settingsSheet': new FakeElement('settingsSheet'),
          '#sheetBackdrop': new FakeElement('sheetBackdrop'),
          '#settingsForm': new FakeElement('settingsForm'),
          '#asrModel': new FakeElement('asrModel'),
          '#asrLanguage': new FakeElement('asrLanguage'),
          '#targetLang': new FakeElement('targetLang'),
          '#translationModel': new FakeElement('translationModel'),
          '#modelCacheDir': new FakeElement('modelCacheDir'),
          '#offlineOnly': new FakeElement('offlineOnly'),
          '#trustRemoteCode': new FakeElement('trustRemoteCode'),
        }};

        const documentListeners = {{}};
        const document = {{
          querySelector(selector) {{
            return elements[selector] ?? null;
          }},
          createElement() {{
            return new FakeElement();
          }},
          addEventListener(type, handler) {{
            documentListeners[type] = handler;
          }},
          body: new FakeElement('body'),
        }};

        const context = {{
          console,
          document,
          window: null,
          location: {{ protocol: 'http:', host: 'example.test' }},
          WebSocket: FakeWebSocket,
          setTimeout(fn) {{ return 1; }},
          clearTimeout() {{}},
          requestAnimationFrame(fn) {{ fn(); }},
          Date,
          JSON,
        }};
        context.window = context;

        vm.runInNewContext({json.dumps(app_source)}, context, {{ filename: 'app.js' }});

        const runScenario = () => {{
        {textwrap.indent(script, "  ")}
        }};

        const result = runScenario();
        process.stdout.write(JSON.stringify(result));
        """
    )
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


@dataclass
class FakeSession:
    status: RuntimeStatus

    def __post_init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class MutatingWebSocket:
    def __init__(self, dashboard: WebDashboard, *, remove_self: bool = False) -> None:
        self._dashboard = dashboard
        self._remove_self = remove_self
        self.messages = []

    async def send_json(self, msg) -> None:
        self.messages.append(msg)
        if self._remove_self:
            self._dashboard._clients.discard(self)
        await asyncio.sleep(0)


class StreamingFakeSession(FakeSession):
    def __init__(self, status: RuntimeStatus, *, subtitle_sink, status_sink) -> None:
        super().__init__(status)
        self._subtitle_sink = subtitle_sink
        self._status_sink = status_sink

    def start(self) -> None:
        super().start()
        self._status_sink.publish(RuntimeStatus(state=RuntimeState.STARTING))
        self._status_sink.publish(RuntimeStatus(state=RuntimeState.RUNNING))
        self._subtitle_sink.publish(
            SubtitleEvent(
                source_text="hello",
                source_language="English",
                translated_text="你好",
                latency_ms=12.5,
            )
        )


def test_status_sink_broadcasts_runtime_state() -> None:
    messages = []
    sink = RuntimeStatusSink(lambda msg: messages.append(msg))

    sink.publish(RuntimeStatus(state=RuntimeState.RUNNING))

    assert messages == [{"type": "status", "state": "running"}]


def test_subtitle_sink_broadcasts_websocket_result_payload() -> None:
    messages = []
    sink = RuntimeSubtitleSink(lambda msg: messages.append(msg))

    sink.publish(
        SubtitleEvent(
            source_text="hello",
            source_language="English",
            translated_text="你好",
            latency_ms=12.5,
        )
    )

    assert messages == [
        {
            "type": "result",
            "original": "hello",
            "translation": "你好",
            "language": "English",
            "latency_ms": 12.5,
        }
    ]


def test_broadcast_uses_client_snapshot_when_client_disconnects(monkeypatch) -> None:
    async def scenario() -> None:
        dashboard = WebDashboard()
        dashboard._loop = asyncio.get_running_loop()
        first = MutatingWebSocket(dashboard, remove_self=True)
        second = MutatingWebSocket(dashboard)
        dashboard._clients = {first, second}
        tasks = []

        def fake_run_coroutine_threadsafe(coro, loop):
            task = loop.create_task(coro)
            tasks.append(task)
            return task

        monkeypatch.setattr(
            web_server.asyncio,
            "run_coroutine_threadsafe",
            fake_run_coroutine_threadsafe,
        )

        dashboard._broadcast({"type": "status", "state": "running"})

        await tasks[0]

        assert first.messages == [{"type": "status", "state": "running"}]
        assert second.messages == [{"type": "status", "state": "running"}]

    asyncio.run(scenario())


def test_stop_message_offloads_session_stop_from_event_loop(monkeypatch) -> None:
    async def scenario() -> None:
        dashboard = WebDashboard()
        session = FakeSession(RuntimeStatus(state=RuntimeState.RUNNING))
        dashboard._session = session
        to_thread_calls = []

        async def fake_to_thread(func, *args, **kwargs):
            to_thread_calls.append((func, args, kwargs))
            return func(*args, **kwargs)

        monkeypatch.setattr(web_server.asyncio, "to_thread", fake_to_thread)

        await dashboard._handle_client_msg(object(), '{"type": "stop"}')

        assert len(to_thread_calls) == 1
        assert to_thread_calls[0][0].__self__ is session
        assert to_thread_calls[0][0].__func__ is FakeSession.stop
        assert session.stop_calls == 1
        assert dashboard._session is None

    asyncio.run(scenario())


def test_start_message_offloads_previous_session_stop(monkeypatch) -> None:
    async def scenario() -> None:
        dashboard = WebDashboard()
        previous_session = FakeSession(RuntimeStatus(state=RuntimeState.STOPPED))
        replacement_session = FakeSession(RuntimeStatus(state=RuntimeState.STARTING))
        dashboard._session = previous_session
        to_thread_calls = []

        async def fake_to_thread(func, *args, **kwargs):
            to_thread_calls.append((func, args, kwargs))
            return func(*args, **kwargs)

        monkeypatch.setattr(web_server.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(
            web_server,
            "build_cli_session",
            lambda cfg, *, subtitle_sink, status_sink: replacement_session,
        )

        await dashboard._handle_client_msg(object(), '{"type": "start"}')

        assert len(to_thread_calls) == 1
        assert to_thread_calls[0][0].__self__ is previous_session
        assert to_thread_calls[0][0].__func__ is FakeSession.stop
        assert previous_session.stop_calls == 1
        assert replacement_session.start_calls == 1
        assert dashboard._session is replacement_session

    asyncio.run(scenario())


async def test_websocket_start_flow_emits_runtime_status_and_results(
    aiohttp_client, monkeypatch
) -> None:
    dashboard = WebDashboard()
    dashboard._loop = asyncio.get_running_loop()

    def fake_build_cli_session(cfg, *, subtitle_sink, status_sink):
        return StreamingFakeSession(
            RuntimeStatus(state=RuntimeState.STOPPED),
            subtitle_sink=subtitle_sink,
            status_sink=status_sink,
        )

    monkeypatch.setattr(web_server, "build_cli_session", fake_build_cli_session)

    client = await aiohttp_client(dashboard._app)
    ws = await client.ws_connect("/ws")

    await ws.send_json({"type": "start"})

    received_status = await ws.receive_json(timeout=1)
    received_running_status = await ws.receive_json(timeout=1)
    received_result = await ws.receive_json(timeout=1)

    assert received_status["type"] == "status"
    assert received_status["state"] in {"starting", "running", "failed"}
    assert received_running_status == {"type": "status", "state": "running"}
    assert set(received_result) >= {
        "type",
        "original",
        "translation",
        "language",
        "latency_ms",
    }

    await ws.close()


def test_frontend_start_button_requires_open_websocket() -> None:
    result = run_frontend_scenario(
        """
        elements['#statusLabel'].textContent = 'Stopped';
        elements['#statusDetail'].textContent = 'Waiting to start';
        elements['#statusIcon'].setAttribute('data-state', 'stopped');
        elements['#btnStart'].dispatchEvent({ type: 'click' });
        return {
          statusLabel: elements['#statusLabel'].textContent,
          statusDetail: elements['#statusDetail'].textContent,
          statusState: elements['#statusIcon'].getAttribute('data-state'),
          sent: FakeWebSocket.instance.sent,
        };
        """
    )

    assert result == {
        "statusLabel": "Stopped",
        "statusDetail": "Waiting to start",
        "statusState": "stopped",
        "sent": [],
    }


def test_frontend_populates_empty_optional_settings_from_backend() -> None:
    result = run_frontend_scenario(
        """
        FakeWebSocket.initialReadyState = FakeWebSocket.OPEN;
        FakeWebSocket.instance.readyState = FakeWebSocket.OPEN;
        elements['#asrLanguage'].value = 'English';
        elements['#modelCacheDir'].value = '/tmp/models';
        FakeWebSocket.instance.onmessage({
          data: JSON.stringify({
            type: 'config',
            asr_model: 'Qwen/Qwen3-ASR-0.6B',
            asr_language: '',
            target_lang: 'zh',
            translation_model: 'tencent/HY-MT1.5-1.8B-GPTQ-Int4',
            model_cache_dir: '',
            offline_only: false,
            trust_remote_code: true,
          }),
        });
        return {
          asrLanguage: elements['#asrLanguage'].value,
          modelCacheDir: elements['#modelCacheDir'].value,
        };
        """
    )

    assert result == {"asrLanguage": "", "modelCacheDir": ""}


def test_frontend_preserves_empty_optional_settings_when_saving() -> None:
    result = run_frontend_scenario(
        """
        FakeWebSocket.instance.readyState = FakeWebSocket.OPEN;
        elements['#asrModel'].value = 'Qwen/Qwen3-ASR-0.6B';
        elements['#asrLanguage'].value = '';
        elements['#targetLang'].value = 'zh';
        elements['#translationModel'].value = 'tencent/HY-MT1.5-1.8B-GPTQ-Int4';
        elements['#modelCacheDir'].value = '';
        elements['#offlineOnly'].checked = false;
        elements['#trustRemoteCode'].checked = true;
        elements['#settingsForm'].dispatchEvent({ type: 'submit' });
        return FakeWebSocket.instance.sent[0];
        """
    )

    assert result == {
        "type": "config",
        "asr_model": "Qwen/Qwen3-ASR-0.6B",
        "asr_language": "",
        "target_lang": "zh",
        "translation_model": "tencent/HY-MT1.5-1.8B-GPTQ-Int4",
        "model_cache_dir": "",
        "offline_only": False,
        "trust_remote_code": True,
    }
