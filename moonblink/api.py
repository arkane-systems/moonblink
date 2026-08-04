"""Local HTTP control API."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


@dataclass(slots=True)
class ControlCallbacks:
    ack: Callable[[str], Any] | None = None
    set_brightness: Callable[[float], Any] | None = None
    test_pattern: Callable[[str], Any] | None = None
    current_state: Callable[[], Any] | None = None


class _RequestHandler(BaseHTTPRequestHandler):
    callbacks: ControlCallbacks = ControlCallbacks()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid-json"})
            return

        if self.path == "/ack":
            alert_id = str(payload.get("alert_id", ""))
            if self.callbacks.ack is not None:
                self.callbacks.ack(alert_id)
            _json_response(self, 200, {"ok": True, "alert_id": alert_id})
            return

        if self.path == "/brightness":
            level = float(payload.get("level", 0.0))
            if self.callbacks.set_brightness is not None:
                self.callbacks.set_brightness(level)
            _json_response(self, 200, {"ok": True, "level": level})
            return

        if self.path == "/test-pattern":
            pattern = str(payload.get("pattern", ""))
            result = None
            if self.callbacks.test_pattern is not None:
                result = self.callbacks.test_pattern(pattern)
            if self.callbacks.current_state is not None and result is None:
                result = self.callbacks.current_state()
            _json_response(self, 200, {"ok": True, "pattern": pattern, "state": result})
            return

        _json_response(self, 404, {"error": "not-found"})

    def log_message(self, format: str, *args: Any) -> None:
        return


@dataclass(slots=True)
class ControlServer:
    bind_address: str = "127.0.0.1"
    port: int = 8765
    callbacks: ControlCallbacks = field(default_factory=ControlCallbacks)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None

    def start(self) -> None:
        _RequestHandler.callbacks = self.callbacks
        self._server = ThreadingHTTPServer((self.bind_address, self.port), _RequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="moonblink-api", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
