from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from moonblink.api import ControlCallbacks, ControlServer


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class ControlApiTests(unittest.TestCase):
    def test_endpoints_round_trip(self) -> None:
        acked: list[str] = []
        brightness: list[float] = []
        patterns: list[str] = []

        server = ControlServer(
            port=0,
            callbacks=ControlCallbacks(
                ack=acked.append,
                set_brightness=brightness.append,
                test_pattern=patterns.append,
                current_state=lambda: {"mode": "idle"},
            ),
        )
        server.start()
        try:
            port = server._server.server_address[1]
            base = f"http://127.0.0.1:{port}"
            self.assertEqual(_post_json(f"{base}/ack", {"alert_id": "abc"}), {"ok": True, "alert_id": "abc"})
            self.assertEqual(_post_json(f"{base}/brightness", {"level": 0.2}), {"ok": True, "level": 0.2})
            response = _post_json(f"{base}/test-pattern", {"pattern": "rainbow"})
            self.assertEqual(response["ok"], True)
            self.assertEqual(acked, ["abc"])
            self.assertEqual(brightness, [0.2])
            self.assertEqual(patterns, ["rainbow"])
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
