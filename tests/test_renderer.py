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

    def test_warning_alert_uses_indicator_pixel(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PAUSED)
        state.add_alert("warn", kind="heater", severity=ALERT_WARNING)
        frame = render_frame(state, RenderConfig(), now=1.0)
        self.assertNotEqual(frame.pixels[7], (0, 0, 0))

    def test_critical_state_overrides_other_visuals(self) -> None:
        state = PrinterState(printer_mode=PRINTER_ERROR)
        state.add_alert("crit", kind="heater", severity=ALERT_CRITICAL)
        frame = render_frame(state, RenderConfig(), now=1.0)
        self.assertTrue(all(pixel == frame.pixels[0] for pixel in frame.pixels))
        self.assertGreater(frame.pixels[0][0], frame.pixels[0][1])
        self.assertGreater(frame.pixels[0][0], frame.pixels[0][2])

    def test_flash_overrides_normal_rendering(self) -> None:
        state = PrinterState(printer_mode=PRINTER_PRINTING)
        state.set_layer_change(12, now=0.0, flash_duration=0.3)
        frame = render_frame(state, RenderConfig(), now=0.1)
        self.assertEqual(frame.mode, "flash")
        self.assertEqual(frame.pixels[0], frame.pixels[1])


if __name__ == "__main__":
    unittest.main()
