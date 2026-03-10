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
from pathlib import Path
from typing import Any

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
        self._clients: set[web.WebSocketResponse] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app = web.Application()
        self._app.router.add_get("/", self._index_handler)
        self._app.router.add_get("/ws", self._ws_handler)
        self._app.router.add_static("/", WEB_DIR, show_index=False)

    # ── aiohttp lifecycle ──────────────────────────────────────────

    def run(self) -> None:
        web.run_app(self._app, host="0.0.0.0", port=self._port, print=self._on_startup)

    def _on_startup(self, msg: str) -> None:
        logger.info(msg)
        self._loop = asyncio.get_event_loop()

    # ── WebSocket handler ──────────────────────────────────────────

    async def _index_handler(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(WEB_DIR / "index.html")

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("Client connected (%d total)", len(self._clients))

        # Send current state
        if self._session is not None:
            status = self._session.status
            await ws.send_json(
                {
                    "type": "status",
                    "state": str(status.state),
                }
            )

        try:
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

        msg_type = msg.get("type", "")

        if msg_type == "start":
            await self._start_engine()
        elif msg_type == "stop":
            await self._stop_engine()
        elif msg_type == "config":
            self._apply_config(msg)
        elif msg_type == "get_config":
            await ws.send_json(self._get_config_msg())

    # ── Session management ─────────────────────────────────────────

    async def _start_engine(self) -> None:
        if self._session is not None:
            status = self._session.status
            if status.state in {RuntimeState.RUNNING, RuntimeState.STARTING}:
                return

            old_session = self._session
            await asyncio.to_thread(old_session.stop)

        self._session = build_cli_session(
            self._cfg,
            subtitle_sink=RuntimeSubtitleSink(self._broadcast),
            status_sink=RuntimeStatusSink(self._broadcast),
        )
        self._session.start()
        logger.info("Session started via web dashboard")

    async def _stop_engine(self) -> None:
        if self._session is not None:
            session = self._session
            await asyncio.to_thread(session.stop)
            self._session = None
            logger.info("Session stopped via web dashboard")

    def _apply_config(self, msg: dict[str, Any]) -> None:
        """Update config from client settings, to be used on next start."""
        if "asr_model" in msg and msg["asr_model"]:
            self._cfg = Config(
                asr_model=msg.get("asr_model", self._cfg.asr_model),
                asr_language=msg.get("asr_language") or None,
                translation_model=msg.get(
                    "translation_model", self._cfg.translation_model
                ),
                translation_target_lang=msg.get(
                    "target_lang", self._cfg.translation_target_lang
                ),
                model_cache_dir=msg.get("model_cache_dir") or None,
                offline_only=msg.get("offline_only", self._cfg.offline_only),
                translation_trust_remote_code=msg.get(
                    "trust_remote_code", self._cfg.translation_trust_remote_code
                ),
            )
        logger.info("Config updated via web dashboard")

    def _get_config_msg(self) -> dict[str, Any]:
        return {
            "type": "config",
            "asr_model": self._cfg.asr_model,
            "asr_language": self._cfg.asr_language or "",
            "target_lang": self._cfg.translation_target_lang,
            "translation_model": self._cfg.translation_model,
            "model_cache_dir": self._cfg.model_cache_dir or "",
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
