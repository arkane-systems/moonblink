"""Async Moonraker connector."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
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

logger = logging.getLogger(__name__)

StateHandler = Callable[[PrinterState], Awaitable[None] | None]


@dataclass(slots=True)
class MoonrakerConfig:
    websocket_url: str = "ws://127.0.0.1/websocket"
    rest_url: str = "http://127.0.0.1"
    poll_interval: float = 5.0
    reconnect_delay: float = 2.0
    max_reconnect_delay: float = 30.0
    # `motion_report` (not `toolhead`) is the object that actually carries
    # real-time velocity (`live_velocity`); `display_status` carries print
    # progress (`toolhead` has neither). `heater_bed`/`extruder` are the
    # common default heaters -- add any additional heaters (extruder1,
    # heater_generic chamber, ...) your printer defines via config.
    objects: tuple[str, ...] = ("print_stats", "display_status", "heater_bed", "extruder", "motion_report")


@dataclass(slots=True)
class MoonrakerConnector:
    config: MoonrakerConfig
    state: PrinterState
    on_state_change: StateHandler | None = None
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    async def start(self) -> None:
        logger.info(
            "moonraker: starting connector (websocket=%s rest=%s)",
            self.config.websocket_url,
            self.config.rest_url,
        )
        if aiohttp is None:
            logger.warning(
                "moonraker: 'aiohttp' is not installed; falling back to REST-only polling "
                "every %.1fs (no realtime websocket updates, install the base requirements "
                "to enable it)",
                self.config.poll_interval,
            )
        await self.refresh_snapshot()
        await self._run_forever()

    def stop(self) -> None:
        logger.info("moonraker: stopping connector")
        self._stop_event.set()

    async def refresh_snapshot(self) -> None:
        try:
            payload = await asyncio.to_thread(self._fetch_snapshot)
        except (OSError, ValueError) as exc:
            # Network failures (OSError, including urllib's URLError/timeout
            # subclasses) or malformed JSON responses (ValueError, including
            # json.JSONDecodeError) shouldn't crash the connector -- REST
            # snapshots are a best-effort sanity check, retried on the next
            # poll/reconnect.
            logger.warning("moonraker: REST snapshot request failed: %s", exc)
            return

        result = payload.get("result", payload)
        status = result.get("status") if isinstance(result, dict) else None
        if isinstance(status, dict):
            self._apply_snapshot(status)
            await self._notify()
            logger.debug("moonraker: REST snapshot applied")
        else:
            logger.warning("moonraker: REST snapshot response had no usable 'status' payload")

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
            except Exception as exc:  # noqa: BLE001 - top-level reconnect loop: any failure (network,
                # protocol, or otherwise) must trigger backoff+retry rather than crash the service.
                logger.warning("moonraker: connection lost/failed (%s); retrying in %.1fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.max_reconnect_delay)

    async def _ws_session(self) -> None:
        if aiohttp is None:
            await asyncio.sleep(self.config.poll_interval)
            await self.refresh_snapshot()
            return

        async with aiohttp.ClientSession() as session, session.ws_connect(self.config.websocket_url, heartbeat=20) as ws:
            logger.info("moonraker: websocket connected to %s", self.config.websocket_url)
            await self._subscribe(ws)
            logger.debug("moonraker: subscribed to objects: %s", ", ".join(self.config.objects))
            poll_task = asyncio.create_task(self._poll_loop())
            try:
                async for message in ws:
                    if self._stop_event.is_set():
                        break
                    if message.type == aiohttp.WSMsgType.TEXT:
                        self._handle_message(message.data)
                    elif message.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE):
                        logger.warning("moonraker: websocket closed/errored (message type=%s)", message.type)
            finally:
                poll_task.cancel()
                with contextlib.suppress(Exception):
                    await poll_task
                logger.info("moonraker: websocket session ended")

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

        method = payload.get("method")
        params = payload.get("params")

        if method == "notify_status_update":
            # Real shape: params == [status_dict, eventtime].
            status = params[0] if isinstance(params, list) and params else None
            if isinstance(status, dict):
                self.state.update_from_status(status)
            else:
                logger.warning("moonraker: notify_status_update had no usable status payload")
        elif method == "notify_gcode_response":
            # Real shape: params == [response_text].
            text = params[0] if isinstance(params, list) and params else None
            if isinstance(text, str) and text:
                self.state.update_from_gcode_response(text)
        elif method:
            logger.debug("moonraker: unhandled notification method=%s", method)
        elif "result" in payload and payload.get("id") is not None:
            # The reply to our `printer.objects.subscribe` request carries
            # an initial status snapshot -- applying it means we don't have
            # to wait for the next REST poll or notification to reflect
            # current state after (re)connecting.
            result = payload["result"]
            status = result.get("status") if isinstance(result, dict) else None
            if isinstance(status, dict):
                self.state.update_from_status(status)
                logger.debug("moonraker: applied subscribe response snapshot")

    def _apply_snapshot(self, status: dict[str, Any]) -> None:
        self.state.update_from_status(status)

    async def _notify(self) -> None:
        if self.on_state_change is None:
            return
        result = self.on_state_change(self.state)
        if asyncio.iscoroutine(result):
            await result
