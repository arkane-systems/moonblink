from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from moonblink.animator import AnimationConfig, FrameAnimator, NullBlinktDriver
from moonblink.renderer import RenderConfig, render_frame
from moonblink.state import PrinterState


class NullDriverInjectionTests(unittest.TestCase):
    """Confirm the DI seam still lets tests run fully without real hardware."""

    def test_fake_driver_receives_frames_without_any_hardware_import(self) -> None:
        driver = NullBlinktDriver()
        animator = FrameAnimator(driver, AnimationConfig(transition_ms=0))
        state = PrinterState()
        import asyncio

        asyncio.run(animator.present(render_frame(state, RenderConfig()), now=0.0))
        animator.clear()  # should not raise


class BlinktHardwareDriverTests(unittest.TestCase):
    def test_raises_clear_error_when_blinkt_unimportable(self) -> None:
        from moonblink.hardware import BlinktHardwareDriver, BlinktHardwareError

        with patch.dict(sys.modules, {"blinkt": None}), self.assertRaises(BlinktHardwareError):
            BlinktHardwareDriver()

    def test_wraps_real_blinkt_module_when_available(self) -> None:
        import types

        fake_blinkt = types.ModuleType("blinkt")
        calls: list[tuple] = []
        fake_blinkt.set_clear_on_exit = lambda value: calls.append(("set_clear_on_exit", value))
        fake_blinkt.set_pixel = lambda *args: calls.append(("set_pixel", args))
        fake_blinkt.show = lambda: calls.append(("show",))
        fake_blinkt.clear = lambda: calls.append(("clear",))

        from moonblink.hardware import BlinktHardwareDriver

        with patch.dict(sys.modules, {"blinkt": fake_blinkt}):
            driver = BlinktHardwareDriver()
            driver.set_pixel(0, 255, 0, 0, 0.5)
            driver.show()
            driver.clear()

        self.assertIn(("set_clear_on_exit", True), calls)
        self.assertIn(("set_pixel", (0, 255, 0, 0, 0.5)), calls)
        self.assertIn(("show",), calls)
        self.assertIn(("clear",), calls)


if __name__ == "__main__":
    unittest.main()
