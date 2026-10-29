"""
Web dashboard for the OBS Live Translator.

Serves a lightweight single-page app and bridges the runtime session
to browser clients via WebSocket.

Usage:
    python web_server.py [--port 8080]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

# Make our modules importable
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from config import Config  # noqa: E402
from subtitle_runtime.application.session import SessionController  # noqa: E402
from subtitle_runtime.domain.events import (  # noqa: E402
    RuntimeState,
    RuntimeStatus,
    SubtitleEvent,
)
from subtitle_runtime.entrypoints.cli import build_cli_session  # noqa: E402

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"


class RuntimeSubtitleSink:
    def __init__(self, emit) -> None:
        self._emit = emit

    def publish(self, event: SubtitleEvent) -> None:
        self._emit(
            {
                "type": "result",
                "original": event.source_text,
                "translation": event.translated_text,
                "language": event.source_language,
                "latency_ms": round(event.latency_ms, 1),
            }
        )


class RuntimeStatusSink:
    def __init__(self, emit) -> None:
        self._emit = emit

    def publish(self, status: RuntimeStatus) -> None:
        self._emit({"type": "status", "state": str(status.state)})


class WebDashboard:
    """aiohttp server bridging the runtime session ↔ WebSocket ↔ browser."""

    def __init__(self, port: int = 8080) -> None:
        self._port = port
        self._cfg = Config()
        self._session: SessionController | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._stop_task: asyncio.Task | None = None
        self._closing = False
        self._clients: set[web.WebSocketResponse] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app = web.Application()
        self._app.on_startup.append(self._startup)
        self._app.on_shutdown.append(self._shutdown)
        self._app.on_cleanup.append(self._cleanup)
        self._app.router.add_get("/", self._index_handler)
        self._app.router.add_get("/ws", self._ws_handler)
        self._app.router.add_static("/", WEB_DIR, show_index=False)

    # ── aiohttp lifecycle ──────────────────────────────────────────

    def run(self) -> None:
        web.run_app(
            self._app, host="127.0.0.1", port=self._port, print=self._on_startup
        )

    def _on_startup(self, msg: str) -> None:
        logger.info(msg)
        self._loop = asyncio.get_event_loop()

    async def _startup(self, app: web.Application) -> None:
        self._loop = asyncio.get_running_loop()

    async def _shutdown(self, app: web.Application) -> None:
        self._closing = True
        for ws in list(self._clients):
            await ws.close(code=1001, message=b"Server shutdown")

    async def _cleanup(self, app: web.Application) -> None:
        self._closing = True
        async with self._lifecycle_lock:
            # Surface incomplete shutdown to the server rather than claiming cleanup.
            if not await self._stop_session():
                raise RuntimeError("Dashboard session cleanup failed")

    # ── WebSocket handler ──────────────────────────────────────────

    async def _index_handler(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(WEB_DIR / "index.html")

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        if self._closing:
            raise web.HTTPServiceUnavailable(text="Server shutting down")
        # Only a local page may control the unauthenticated local runtime.
        # Validate Host as well as Origin to reject browser DNS rebinding.
        try:
            target = urlsplit(f"{request.scheme}://{request.host}")
            if target.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("non-local host")
            origin = request.headers.get("Origin")
            if origin is not None:
                source = urlsplit(origin)
                def endpoint(url):
                    return (url.scheme, url.hostname,
                            url.port or (443 if url.scheme == "https" else 80))
                if (source.scheme not in {"http", "https"} or
                        source.username is not None or source.password is not None or
                        source.path or source.query or source.fragment or
                        endpoint(source) != endpoint(target)):
                    raise ValueError("cross-origin client")
        except ValueError:
            raise web.HTTPForbidden(text="Local same-origin clients only") from None
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if self._closing:
            await ws.close(code=1001, message=b"Server shutdown")
            return ws
        self._clients.add(ws)
        logger.info("Client connected (%d total)", len(self._clients))

        try:
            # Send current state
            if self._session is not None:
                status = self._session.status
                await ws.send_json(
                    {
                        "type": "status",
                        "state": str(status.state),
                    }
                )

            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_client_msg(ws, msg.data)
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)
            logger.info("Client disconnected (%d remaining)", len(self._clients))

        return ws

    async def _handle_client_msg(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not isinstance(msg, dict):
            return
        msg_type = msg.get("type", "")

        if msg_type == "start":
            await self._start_engine()
        elif msg_type == "stop":
            await self._stop_engine()
        elif msg_type == "config":
            try:
                self._apply_config(msg)
            except ValueError as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
        elif msg_type == "get_config":
            await ws.send_json(self._get_config_msg())

    # ── Session management ─────────────────────────────────────────

    def _publish_stop_failure(self) -> None:
        self._broadcast({"type": "status", "state": str(RuntimeState.FAILED)})

    def _observe_stop(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error("Background session stop failed: %s", error)

    async def _stop_session(self) -> bool:
        """Called under the lifecycle lock; retain an in-flight stop on cancellation."""
        if self._session is None:
            return True
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(asyncio.to_thread(self._session.stop))
            # Observe failures even if the requesting client has gone away.
            # Awaiting this task later still raises and preserves retry semantics.
            self._stop_task.add_done_callback(self._observe_stop)
        try:
            # Cancelling a websocket handler cannot stop its underlying thread.
            # The next lifecycle operation must await this same owned task.
            await asyncio.shield(self._stop_task)
        except Exception:
            self._stop_task = None
            logger.exception("Failed to stop session via web dashboard")
            self._publish_stop_failure()
            return False
        self._stop_task = None
        self._session = None
        return True

    async def _start_engine(self) -> None:
        async with self._lifecycle_lock:
            if self._closing:
                return
            if self._session is not None:
                status = self._session.status
                if (self._stop_task is None and
                        status.state in {RuntimeState.RUNNING, RuntimeState.STARTING}):
                    return
                if not await self._stop_session():
                    return
            # Shutdown may have started while the previous stop was awaited.
            if self._closing:
                return
            self._session = build_cli_session(
                self._cfg,
                subtitle_sink=RuntimeSubtitleSink(self._broadcast),
                status_sink=RuntimeStatusSink(self._broadcast),
            )
            self._session.start()
            logger.info("Session started via web dashboard")

    async def _stop_engine(self) -> None:
        async with self._lifecycle_lock:
            if await self._stop_session():
                logger.info("Session stopped via web dashboard")

    def _apply_config(self, msg: dict[str, Any]) -> None:
        """Update config from client settings, to be used on next start."""
        fields = {
            "asr_model": "asr_model", "asr_language": "asr_language",
            "translation_model": "translation_model",
            "target_lang": "translation_target_lang",
            "model_cache_dir": "model_cache_dir", "offline_only": "offline_only",
            "vad_model_path": "vad_model_path",
            "trust_remote_code": "translation_trust_remote_code",
        }
        changes = {}
        for key, field in fields.items():
            if key not in msg:
                continue
            value = msg[key]
            if key in {"offline_only", "trust_remote_code"}:
                if type(value) is not bool:
                    raise ValueError(f"{key} must be a boolean")
            elif key in {"asr_language", "model_cache_dir", "vad_model_path"}:
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"{key} must be a string or null")
                value = value.strip() or None if isinstance(value, str) else None
            else:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{key} must be a non-empty string")
                value = value.strip()
            changes[field] = value
        # Validate the whole message before replacing; preserve non-UI settings.
        self._cfg = replace(self._cfg, **changes)
        logger.info("Config updated via web dashboard")

    def _get_config_msg(self) -> dict[str, Any]:
        return {
            "type": "config",
            "asr_model": self._cfg.asr_model,
            "asr_language": self._cfg.asr_language or "",
            "target_lang": self._cfg.translation_target_lang,
            "translation_model": self._cfg.translation_model,
            "model_cache_dir": self._cfg.model_cache_dir or "",
            "vad_model_path": self._cfg.vad_model_path or "",
            "offline_only": self._cfg.offline_only,
            "trust_remote_code": self._cfg.translation_trust_remote_code,
        }

    def _broadcast(self, msg: dict[str, Any]) -> None:
        """Thread-safe broadcast to all connected WebSocket clients."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        async def _send() -> None:
            stale: list[web.WebSocketResponse] = []
            for ws in list(self._clients):
                try:
                    await ws.send_json(msg)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._clients.discard(ws)

        asyncio.run_coroutine_threadsafe(_send(), loop)


def main() -> None:
    parser = argparse.ArgumentParser(description="OBS Live Translator — Web Dashboard")
    parser.add_argument(
        "--port", type=int, default=8080, help="HTTP port (default: 8080)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
        stream=sys.stderr,
    )

    dashboard = WebDashboard(port=args.port)
    logger.info("Starting web dashboard on http://localhost:%d", args.port)
    dashboard.run()


if __name__ == "__main__":
    main()
