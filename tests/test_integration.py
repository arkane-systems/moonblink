from __future__ import annotations

import unittest

from moonblink.connector import MoonrakerConfig, MoonrakerConnector
from moonblink.renderer import RenderConfig, render_frame
from moonblink.state import ALERT_CRITICAL, ALERT_WARNING, PRINTER_PAUSED, PRINTER_PRINTING, PrinterState


class IntegrationFlowTests(unittest.TestCase):
    def test_event_sequence_changes_rendered_frame(self) -> None:
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)

        connector._handle_message(
            '{"method":"notify_status_update","params":[{"print_stats":{"state":"printing"},'
            '"display_status":{"progress":0.25}},0.0]}'
        )
        printing = render_frame(state, RenderConfig(), now=0.0)
        self.assertEqual(printing.mode, PRINTER_PRINTING)

        state.set_layer_change(12, now=0.0)
        flash = render_frame(state, RenderConfig(), now=0.1)
        self.assertEqual(flash.mode, "flash")

        state.set_printer_mode(PRINTER_PAUSED, now=1.0)
        state.add_alert("warn", kind="heater", severity=ALERT_WARNING)
        # Pausing auto-triggers a brief "user-effect" pulse (priority 6) that
        # would otherwise mask the steady paused-mode frame we want to
        # assert on here -- render after it's expired (default duration is
        # 0.5s) to see the settled paused state.
        paused = render_frame(state, RenderConfig(), now=1.6)
        self.assertEqual(paused.pixels[0], (255, 255, 0))
        self.assertNotEqual(paused.pixels[7], (0, 0, 0))

        state.clear_all_alerts()
        state.add_alert("crit", kind="heater", severity=ALERT_CRITICAL, now=2.0)
        critical = render_frame(state, RenderConfig(), now=2.0)
        # A freshly-raised critical alert should blink the pixel-7 indicator,
        # not immediately take over the whole strip -- that's reserved for
        # printer_mode == error or an alert that's escalated after being
        # left unacknowledged.
        self.assertEqual(critical.mode, "critical-alert")
        self.assertFalse(all(pixel == critical.pixels[0] for pixel in critical.pixels))

        escalated = render_frame(state, RenderConfig(), now=2.0 + RenderConfig().critical_alert_escalate_after_s)
        self.assertEqual(escalated.mode, "critical")
        self.assertTrue(all(pixel == escalated.pixels[0] for pixel in escalated.pixels))

    def test_progress_temperature_and_layer_change_from_realistic_status_updates(self) -> None:
        """Exercises the full connector -> state -> renderer path with
        Moonraker-shaped `notify_status_update` payloads end-to-end, the way
        a real print would drive it (progress bar filling, motion spark,
        heater warning indicator, and a layer-change flash)."""
        state = PrinterState()
        connector = MoonrakerConnector(MoonrakerConfig(), state)

        connector._handle_message(
            '{"method":"notify_status_update","params":[{'
            '"print_stats":{"state":"printing","info":{"current_layer":1}},'
            '"display_status":{"progress":0.5},'
            '"heater_bed":{"temperature":50.0,"target":60.0},'
            '"motion_report":{"live_velocity":30.0}'
            '},10.0]}'
        )
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0)
        frame = render_frame(state, RenderConfig(), now=10.0)
        self.assertEqual(frame.mode, PRINTER_PRINTING)
        # Progress bar (pixels 1-6): at 50% (3 of 6) some pixels should now
        # be lit with the progress gradient, not left black.
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in frame.pixels[1:7]))
        # Off-target heater indicator (pixel 7) should be lit (warning).
        self.assertNotEqual(frame.pixels[7], (0, 0, 0))

        # A subsequent layer change should trigger the full-strip flash.
        connector._handle_message(
            '{"method":"notify_status_update","params":[{"print_stats":{"state":"printing","info":{"current_layer":2}}},20.0]}'
        )
        flash = render_frame(state, RenderConfig(), now=20.05)
        self.assertEqual(flash.mode, "flash")


if __name__ == "__main__":
    unittest.main()
