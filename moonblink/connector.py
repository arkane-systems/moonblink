"""Async Moonraker connector."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:  # pragma: no cover - optional dependency
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

from .state import PrinterState

StateHandler = Callable[[PrinterState], Awaitable[None] | None]


@dataclass(slots=True)
class MoonrakerConfig:
    websocket_url: str = "ws://127.0.0.1/websocket"
    rest_url: str = "http://127.0.0.1"
    poll_interval: float = 5.0
    reconnect_delay: float = 2.0
    max_reconnect_delay: float = 30.0
    objects: tuple[str, ...] = ("print_stats", "toolhead", "heater_bed", "display_status")


@dataclass(slots=True)
class MoonrakerConnector:
    config: MoonrakerConfig
    state: PrinterState
    on_state_change: StateHandler | None = None
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    async def start(self) -> None:
        await self.refresh_snapshot()
        await self._run_forever()

    def stop(self) -> None:
        self._stop_event.set()

    async def refresh_snapshot(self) -> None:
        try:
            payload = await asyncio.to_thread(self._fetch_snapshot)
        except (OSError, ValueError):
            # Network failures (OSError, including urllib's URLError/timeout
            # subclasses) or malformed JSON responses (ValueError, including
            # json.JSONDecodeError) shouldn't crash the connector -- REST
            # snapshots are a best-effort sanity check, retried on the next
            # poll/reconnect.
            return

        result = payload.get("result", payload)
        status = result.get("status") if isinstance(result, dict) else None
        if isinstance(status, dict):
            self._apply_snapshot(status)
            await self._notify()

    def _fetch_snapshot(self) -> dict[str, Any]:
        query = urlencode({name: "" for name in self.config.objects})
        request = Request(f"{self.config.rest_url.rstrip('/')}/printer/objects/query?{query}")
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _run_forever(self) -> None:
        delay = self.config.reconnect_delay
        while not self._stop_event.is_set():
            try:
                await self._ws_session()
                delay = self.config.reconnect_delay
            except Exception:  # noqa: BLE001 - top-level reconnect loop: any failure (network,
                # protocol, or otherwise) must trigger backoff+retry rather than crash the service.
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.max_reconnect_delay)

    async def _ws_session(self) -> None:
        if aiohttp is None:
            await asyncio.sleep(self.config.poll_interval)
            await self.refresh_snapshot()
            return

        async with aiohttp.ClientSession() as session, session.ws_connect(self.config.websocket_url, heartbeat=20) as ws:
            await self._subscribe(ws)
            poll_task = asyncio.create_task(self._poll_loop())
            try:
                async for message in ws:
                    if self._stop_event.is_set():
                        break
                    if message.type == aiohttp.WSMsgType.TEXT:
                        self._handle_message(message.data)
            finally:
                poll_task.cancel()
                with contextlib.suppress(Exception):
                    await poll_task

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self.config.poll_interval)
            await self.refresh_snapshot()

    async def _subscribe(self, ws: Any) -> None:
        request = {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": [{"objects": {name: None for name in self.config.objects}}],
            "id": 1,
        }
        await ws.send_json(request)

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self.state.update_from_gcode_response(message)
            return

        if not isinstance(payload, dict):
            return

        method = payload.get("method") or payload.get("event") or payload.get("notification")
        params = payload.get("params") or payload.get("result") or {}
        if isinstance(params, list) and params:
            params = params[0]
        if not isinstance(params, dict):
            params = {}

        if method in {"notify_status_update", "status_update"}:
            self.state.update_from_status(params)
        elif method in {"notify_print_progress", "print_progress"}:
            self.state.set_progress(params.get("progress"), elapsed=params.get("elapsed"), remaining=params.get("remaining"))
        elif method in {"notify_temperature_update", "temperature_update"}:
            self.state.update_from_temperature(params)
        elif method in {"notify_motion_update", "motion_update"}:
            self.state.update_from_motion(params)
        elif method in {"notify_layer_change", "layer_change"}:
            self.state.update_from_layer_change(params)
        elif method in {"notify_gcode_response", "gcode_response"}:
            text = params.get("response") or params.get("message") or ""
            if text:
                self.state.update_from_gcode_response(str(text))

    def _apply_snapshot(self, status: dict[str, Any]) -> None:
        self.state.update_from_status(status)
        if "temperature" in status and isinstance(status["temperature"], dict):
            self.state.update_from_temperature(status["temperature"])
        if "toolhead" in status and isinstance(status["toolhead"], dict):
            self.state.update_from_motion(status["toolhead"])

    async def _notify(self) -> None:
        if self.on_state_change is None:
            return
        result = self.on_state_change(self.state)
        if asyncio.iscoroutine(result):
            await result
