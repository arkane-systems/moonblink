from __future__ import annotations

import unittest
from unittest.mock import patch

from moonblink.connector import MoonrakerConfig, MoonrakerConnector
from moonblink.state import PRINTER_PRINTING, PrinterState


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_refresh_updates_state(self) -> None:
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)
        with patch.object(
            MoonrakerConnector,
            "_fetch_snapshot",
            return_value={
                "result": {
                    "status": {
                        "print_stats": {"state": PRINTER_PRINTING},
                        "display_status": {"progress": 0.42},
                    }
                }
            },
        ):
            await connector.refresh_snapshot()
        self.assertEqual(state.printer_mode, PRINTER_PRINTING)
        self.assertAlmostEqual(state.progress, 0.42, places=2)

    async def test_status_update_notification_updates_state(self) -> None:
        # Real Moonraker shape: {"method": "notify_status_update", "params": [status, eventtime]}.
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)
        connector._handle_message(
            '{"method":"notify_status_update","params":[{"print_stats":{"state":"printing"},'
            '"display_status":{"progress":0.66}},123.4]}'
        )
        self.assertEqual(state.printer_mode, PRINTER_PRINTING)
        self.assertAlmostEqual(state.progress, 0.66, places=2)

    async def test_gcode_response_notification_updates_state(self) -> None:
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)
        connector._handle_message('{"method":"notify_gcode_response","params":["Error: Extrude below minimum temp"]}')
        self.assertTrue(state.active_alerts)

    async def test_subscribe_response_applies_initial_snapshot(self) -> None:
        # Moonraker replies to our printer.objects.subscribe request with an
        # initial status snapshot in `result.status` -- we should apply it
        # immediately rather than waiting on the next REST poll.
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)
        connector._handle_message(
            '{"id":1,"result":{"status":{"print_stats":{"state":"printing"},"display_status":{"progress":0.1}}}}'
        )
        self.assertEqual(state.printer_mode, PRINTER_PRINTING)
        self.assertAlmostEqual(state.progress, 0.1, places=2)


if __name__ == "__main__":
    unittest.main()
