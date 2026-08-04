from __future__ import annotations

import unittest

from moonblink.state import ALERT_CRITICAL, ALERT_WARNING, PRINTER_PRINTING, PrinterState


class StateModelTests(unittest.TestCase):
    def test_status_and_progress_are_normalized(self) -> None:
        state = PrinterState()
        state.update_from_status({"printer_state": PRINTER_PRINTING, "progress": 1.5})
        self.assertEqual(state.printer_mode, PRINTER_PRINTING)
        self.assertEqual(state.progress, 1.0)

    def test_temperatures_and_motion_are_recorded(self) -> None:
        state = PrinterState()
        state.update_from_temperature({"heater_bed": {"actual": 57.2, "target": 60}})
        state.update_from_motion({"active": True, "velocity": 120.0})
        self.assertEqual(state.temperatures["heater_bed"].actual, 57.2)
        self.assertTrue(state.motion_active)
        self.assertEqual(state.motion_velocity, 120.0)

    def test_alert_lifecycle(self) -> None:
        state = PrinterState()
        state.add_alert("runout", kind="filament", severity=ALERT_WARNING, message="Filament runout")
        state.add_alert("thermal", kind="heater", severity=ALERT_CRITICAL, message="Thermal runaway")
        self.assertTrue(state.has_warning_alert)
        self.assertTrue(state.has_critical_alert)
        state.acknowledge_alert("thermal")
        self.assertFalse(state.has_critical_alert)
        state.clear_alert("runout")
        self.assertEqual(state.active_alerts, [])


if __name__ == "__main__":
    unittest.main()
