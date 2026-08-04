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

    def test_temperature_threshold_generates_and_clears_warning_alert(self) -> None:
        state = PrinterState()
        state.set_temperature("extruder", actual=210.0, target=200.0)  # 10C off, within warning band
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0)
        self.assertTrue(state.has_warning_alert)
        self.assertFalse(state.has_critical_alert)
        self.assertIn("heater-extruder", state.alerts)
        self.assertAlmostEqual(state.alerts["heater-extruder"].magnitude, 10.0 / 15.0, places=3)

        state.set_temperature("extruder", actual=200.0, target=200.0)  # back on target
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0)
        self.assertFalse(state.has_warning_alert)
        self.assertNotIn("heater-extruder", state.alerts)

    def test_temperature_threshold_generates_critical_alert(self) -> None:
        state = PrinterState()
        state.set_temperature("heater_bed", actual=140.0, target=110.0)  # 30C off
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0)
        self.assertTrue(state.has_critical_alert)
        self.assertEqual(state.alerts["heater-heater_bed"].magnitude, 1.0)

    def test_heater_with_zero_target_is_not_flagged(self) -> None:
        state = PrinterState()
        state.set_temperature("heater_bed", actual=35.0, target=0.0)  # heater off, cooling down
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0)
        self.assertFalse(state.has_warning_alert)
        self.assertFalse(state.has_critical_alert)

    def test_reasserting_alert_preserves_created_at_and_acknowledgement(self) -> None:
        state = PrinterState()
        state.add_alert("runout", kind="filament", severity=ALERT_WARNING, now=1.0)
        state.acknowledge_alert("runout")
        # Same underlying condition re-reported later shouldn't reset the
        # alert's age or un-acknowledge it.
        state.add_alert("runout", kind="filament", severity=ALERT_WARNING, now=50.0)
        self.assertEqual(state.alerts["runout"].created_at, 1.0)
        self.assertTrue(state.alerts["runout"].acknowledged)


if __name__ == "__main__":
    unittest.main()
