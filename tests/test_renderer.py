from __future__ import annotations

import unittest

from moonblink.renderer import RenderConfig, render_frame
from moonblink.state import ALERT_CRITICAL, ALERT_WARNING, PRINTER_ERROR, PRINTER_IDLE, PRINTER_PAUSED, PRINTER_PRINTING, PrinterState


class RendererTests(unittest.TestCase):
    def test_idle_renders_blue_state_pixel(self) -> None:
        frame = render_frame(PrinterState(printer_mode=PRINTER_IDLE), RenderConfig(), now=0.0)
        self.assertEqual(frame.mode, PRINTER_IDLE)
        self.assertEqual(frame.pixels[0], (0, 0, 255))

    def test_printing_renders_progress_and_motion(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PRINTING, progress=0.5, motion_active=True)
        frame = render_frame(state, RenderConfig(), now=1.0)
        self.assertEqual(frame.pixels[0], (0, 255, 0))
        self.assertNotEqual(frame.pixels[1], (0, 0, 0))
        self.assertTrue(any(max(pixel) >= 200 for pixel in frame.pixels))

    def test_reverse_progress_fill_lights_from_pixel_six_toward_one(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PRINTING, progress=0.5)
        frame = render_frame(state, RenderConfig(reverse_progress_fill=True), now=1.0)
        self.assertEqual(frame.pixels[0], (0, 255, 0))
        self.assertNotEqual(frame.pixels[6], (0, 0, 0))
        self.assertEqual(frame.pixels[1], (0, 0, 0))

    def test_reverse_progress_fill_applies_to_paused_mode(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PAUSED, progress=0.5)
        frame = render_frame(state, RenderConfig(reverse_progress_fill=True), now=1.0)
        self.assertEqual(frame.pixels[0], (255, 255, 0))
        self.assertNotEqual(frame.pixels[6], (0, 0, 0))
        self.assertEqual(frame.pixels[1], (0, 0, 0))

    def test_reverse_progress_fill_does_not_change_pixel_zero_or_seven_roles(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PAUSED, progress=0.5)
        state.add_alert("warn", kind="heater", severity=ALERT_WARNING)
        frame = render_frame(state, RenderConfig(reverse_progress_fill=True), now=1.0)
        self.assertEqual(frame.pixels[0], (255, 255, 0))
        self.assertNotEqual(frame.pixels[7], (0, 0, 0))

    def test_motion_spark_ping_pongs_instead_of_wrapping(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PRINTING, progress=1.0, motion_active=True)
        config = RenderConfig()

        # Forward sweep to the far end.
        to_end = render_frame(state, config, now=1.25)
        self.assertEqual(to_end.pixels[6], (230, 230, 230))

        # Then it should move back instead of jumping to pixel 1.
        returning = render_frame(state, config, now=1.5)
        self.assertEqual(returning.pixels[5], (230, 230, 230))
        self.assertNotEqual(returning.pixels[1], (230, 230, 230))

    def test_warning_alert_uses_indicator_pixel(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PAUSED)
        state.add_alert("warn", kind="heater", severity=ALERT_WARNING)
        frame = render_frame(state, RenderConfig(), now=1.0)
        self.assertNotEqual(frame.pixels[7], (0, 0, 0))

    def test_critical_state_overrides_other_visuals(self) -> None:
        state = PrinterState(printer_mode=PRINTER_ERROR)
        state.add_alert("crit", kind="heater", severity=ALERT_CRITICAL, now=1.0)
        frame = render_frame(state, RenderConfig(), now=1.0)
        self.assertTrue(all(pixel == frame.pixels[0] for pixel in frame.pixels))
        self.assertGreater(frame.pixels[0][0], frame.pixels[0][1])
        self.assertGreater(frame.pixels[0][0], frame.pixels[0][2])

    def test_printer_error_is_always_immediate_full_strobe(self) -> None:
        # printer_mode == error must strobe immediately, with no escalation
        # delay, unlike a critical *alert*.
        state = PrinterState(printer_mode=PRINTER_ERROR)
        frame = render_frame(state, RenderConfig(), now=0.0)
        self.assertEqual(frame.mode, "critical")
        self.assertTrue(all(pixel == frame.pixels[0] for pixel in frame.pixels))

    def test_fresh_critical_alert_blinks_pixel_seven_only(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PAUSED)
        state.add_alert("thermal", kind="heater", severity=ALERT_CRITICAL, now=0.0)
        frame = render_frame(state, RenderConfig(), now=0.0)
        self.assertEqual(frame.mode, "critical-alert")
        self.assertEqual(frame.pixels[0], (255, 255, 0))  # paused color untouched
        self.assertFalse(all(pixel == frame.pixels[0] for pixel in frame.pixels))

    def test_critical_alert_escalates_to_full_strobe_after_timeout(self) -> None:
        config = RenderConfig(critical_alert_escalate_after_s=10.0)
        state = PrinterState(printer_mode=PRINTER_PAUSED)
        state.add_alert("thermal", kind="heater", severity=ALERT_CRITICAL, now=0.0)

        still_blinking = render_frame(state, config, now=5.0)
        self.assertEqual(still_blinking.mode, "critical-alert")

        escalated = render_frame(state, config, now=10.5)
        self.assertEqual(escalated.mode, "critical")
        self.assertTrue(all(pixel == escalated.pixels[0] for pixel in escalated.pixels))

    def test_acknowledging_critical_alert_prevents_escalation(self) -> None:
        config = RenderConfig(critical_alert_escalate_after_s=10.0)
        state = PrinterState(printer_mode=PRINTER_PAUSED)
        state.add_alert("thermal", kind="heater", severity=ALERT_CRITICAL, now=0.0)
        state.acknowledge_alert("thermal")

        frame = render_frame(state, config, now=100.0)
        self.assertNotEqual(frame.mode, "critical")

    def test_pixel_seven_brightness_scales_with_alert_magnitude(self) -> None:
        state_dim = PrinterState(printer_mode=PRINTER_PAUSED)
        state_dim.add_alert("warn", kind="heater", severity=ALERT_WARNING, now=0.0)
        state_dim.alerts["warn"].magnitude = 0.1

        state_bright = PrinterState(printer_mode=PRINTER_PAUSED)
        state_bright.add_alert("warn", kind="heater", severity=ALERT_WARNING, now=0.0)
        state_bright.alerts["warn"].magnitude = 1.0

        # Sample at a phase of the pulse where brightness scaling is visible.
        dim_frame = render_frame(state_dim, RenderConfig(), now=0.25)
        bright_frame = render_frame(state_bright, RenderConfig(), now=0.25)
        self.assertLess(max(dim_frame.pixels[7]), max(bright_frame.pixels[7]))

    def test_flash_overrides_normal_rendering(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PRINTING)
        state.set_layer_change(12, now=0.0, flash_duration=0.3)
        frame = render_frame(state, RenderConfig(), now=0.1)
        self.assertEqual(frame.mode, "flash")
        self.assertEqual(frame.pixels[0], frame.pixels[1])


if __name__ == "__main__":
    unittest.main()
