from __future__ import annotations

import unittest

from moonblink.connector import MoonrakerConfig, MoonrakerConnector
from moonblink.renderer import RenderConfig, render_frame
from moonblink.state import ALERT_CRITICAL, ALERT_WARNING, PRINTER_PAUSED, PRINTER_PRINTING, PrinterState


class IntegrationFlowTests(unittest.TestCase):
    def test_event_sequence_changes_rendered_frame(self) -> None:
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)

        connector._handle_message('{"method":"notify_status_update","params":{"state":"printing"}}')
        connector._handle_message('{"method":"notify_print_progress","params":{"progress":0.25}}')
        printing = render_frame(state, RenderConfig(), now=0.0)
        self.assertEqual(printing.mode, PRINTER_PRINTING)

        state.set_layer_change(12, now=0.0)
        flash = render_frame(state, RenderConfig(), now=0.1)
        self.assertEqual(flash.mode, "flash")

        state.set_printer_mode(PRINTER_PAUSED)
        state.add_alert("warn", kind="heater", severity=ALERT_WARNING)
        paused = render_frame(state, RenderConfig(), now=1.0)
        self.assertEqual(paused.pixels[0], (255, 255, 0))
        self.assertNotEqual(paused.pixels[7], (0, 0, 0))

        state.clear_all_alerts()
        state.add_alert("crit", kind="heater", severity=ALERT_CRITICAL, now=1.0)
        critical = render_frame(state, RenderConfig(), now=1.0)
        # A freshly-raised critical alert should blink the pixel-7 indicator,
        # not immediately take over the whole strip -- that's reserved for
        # printer_mode == error or an alert that's escalated after being
        # left unacknowledged.
        self.assertEqual(critical.mode, "critical-alert")
        self.assertFalse(all(pixel == critical.pixels[0] for pixel in critical.pixels))

        escalated = render_frame(state, RenderConfig(), now=1.0 + RenderConfig().critical_alert_escalate_after_s)
        self.assertEqual(escalated.mode, "critical")
        self.assertTrue(all(pixel == escalated.pixels[0] for pixel in escalated.pixels))


if __name__ == "__main__":
    unittest.main()
