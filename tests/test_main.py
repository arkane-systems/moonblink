from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from moonblink.animator import ConsoleEchoDriver, NullBlinktDriver
from moonblink.config import MoonblinkConfig
from moonblink.main import MoonblinkRuntime
from moonblink.state import PrinterState


def _runtime(*, simulate: bool) -> MoonblinkRuntime:
    config = MoonblinkConfig()
    return MoonblinkRuntime(
        state=PrinterState(),
        renderer_config=config.render,
        animation_config=config.animation,
        moonraker_config=config.moonraker,
        config=config,
        simulate=simulate,
    )


class BuildDriverTests(unittest.TestCase):
    """--simulate should use real Blinkt! hardware when available, console-only otherwise."""

    def test_simulate_falls_back_to_console_only_without_hardware(self) -> None:
        runtime = _runtime(simulate=True)
        with patch.dict(sys.modules, {"blinkt": None}):
            driver = runtime._build_driver()

        self.assertIsInstance(driver, ConsoleEchoDriver)
        self.assertIsInstance(driver._inner, NullBlinktDriver)

    def test_simulate_uses_real_hardware_when_available(self) -> None:
        fake_blinkt = types.ModuleType("blinkt")
        fake_blinkt.set_clear_on_exit = lambda value: None
        fake_blinkt.set_pixel = lambda *args: None
        fake_blinkt.show = lambda: None
        fake_blinkt.clear = lambda: None

        runtime = _runtime(simulate=True)
        with patch.dict(sys.modules, {"blinkt": fake_blinkt}):
            driver = runtime._build_driver()

        self.assertIsInstance(driver, ConsoleEchoDriver)
        self.assertEqual(type(driver._inner).__name__, "BlinktHardwareDriver")

    def test_live_mode_fails_fast_without_hardware(self) -> None:
        runtime = _runtime(simulate=False)
        with patch.dict(sys.modules, {"blinkt": None}), self.assertRaises(SystemExit):
            runtime._build_driver()


if __name__ == "__main__":
    unittest.main()
