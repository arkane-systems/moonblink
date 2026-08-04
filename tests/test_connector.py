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
            return_value={"result": {"status": {"print_stats": {"state": PRINTER_PRINTING, "progress": 0.42}}}},
        ):
            await connector.refresh_snapshot()
        self.assertEqual(state.printer_mode, PRINTER_PRINTING)
        self.assertAlmostEqual(state.progress, 0.42, places=2)

    async def test_json_messages_update_state(self) -> None:
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)
        connector._handle_message('{"method":"notify_status_update","params":{"state":"printing"}}')
        connector._handle_message('{"method":"notify_print_progress","params":{"progress":0.66}}')
        self.assertEqual(state.printer_mode, PRINTER_PRINTING)
        self.assertAlmostEqual(state.progress, 0.66, places=2)


if __name__ == "__main__":
    unittest.main()
