from __future__ import annotations

import unittest

from moonblink.state import (
    ALERT_CRITICAL,
    ALERT_WARNING,
    PRINTER_IDLE,
    PRINTER_PRINTING,
    USER_EFFECT_PAUSE,
    USER_EFFECT_RESUME,
    PrinterState,
)


class StateModelTests(unittest.TestCase):
    def test_status_and_progress_are_normalized(self) -> None:
        # Real Moonraker shape: a per-object mapping, not flat top-level
        # "printer_state"/"progress" keys.
        state = PrinterState()
        state.update_from_status({"print_stats": {"state": "printing"}, "display_status": {"progress": 1.5}})
        self.assertEqual(state.printer_mode, PRINTER_PRINTING)
        self.assertEqual(state.progress, 1.0)

    def test_print_stats_state_aliases_are_normalized_to_idle(self) -> None:
        state = PrinterState()
        for raw in ("standby", "complete", "cancelled"):
            state.update_from_status({"print_stats": {"state": raw}})
            self.assertEqual(state.printer_mode, PRINTER_IDLE, msg=f"{raw!r} should normalize to idle")

    def test_heater_objects_are_recorded_from_status(self) -> None:
        state = PrinterState()
        state.update_from_status({"heater_bed": {"temperature": 57.2, "target": 60}, "extruder": {"temperature": 195.0, "target": 200.0}})
        self.assertEqual(state.temperatures["heater_bed"].actual, 57.2)
        self.assertEqual(state.temperatures["extruder"].target, 200.0)

    def test_motion_report_live_velocity_drives_motion_active(self) -> None:
        state = PrinterState()
        state.update_from_status({"motion_report": {"live_velocity": 45.0}})
        self.assertTrue(state.motion_active)
        self.assertEqual(state.motion_velocity, 45.0)

        state.update_from_status({"motion_report": {"live_velocity": 0.0}})
        self.assertFalse(state.motion_active)

    def test_layer_change_is_detected_from_print_stats_info_diff(self) -> None:
        state = PrinterState()
        # The first observed layer just establishes a baseline -- it
        # shouldn't itself trigger a flash.
        state.update_from_status({"print_stats": {"state": "printing", "info": {"current_layer": 1}}}, now=0.0)
        self.assertEqual(state.flash_until, 0.0)

        state.update_from_status({"print_stats": {"state": "printing", "info": {"current_layer": 2}}}, now=10.0)
        self.assertGreater(state.flash_until, 10.0)

    def test_pause_and_resume_transitions_trigger_user_effect(self) -> None:
        state = PrinterState()
        state.update_from_status({"print_stats": {"state": "printing"}}, now=0.0)
        state.update_from_status({"print_stats": {"state": "paused"}}, now=1.0)
        self.assertEqual(state.user_effect.kind, USER_EFFECT_PAUSE)
        self.assertTrue(state.user_effect.active(1.1))

        state.update_from_status({"print_stats": {"state": "printing"}}, now=2.0)
        self.assertEqual(state.user_effect.kind, USER_EFFECT_RESUME)
        self.assertTrue(state.user_effect.active(2.1))

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
        state.set_temperature("extruder", actual=210.0, target=200.0, now=0.0)  # 10C off, within warning band
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=10.0)
        self.assertTrue(state.has_warning_alert)
        self.assertFalse(state.has_critical_alert)
        self.assertIn("heater-extruder", state.alerts)
        self.assertAlmostEqual(state.alerts["heater-extruder"].magnitude, 10.0 / 15.0, places=3)

        state.set_temperature("extruder", actual=200.0, target=200.0, now=11.0)  # back on target
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=11.0)
        self.assertFalse(state.has_warning_alert)
        self.assertNotIn("heater-extruder", state.alerts)

    def test_temperature_threshold_generates_critical_alert(self) -> None:
        state = PrinterState()
        state.set_temperature("heater_bed", actual=140.0, target=110.0, now=0.0)  # 30C off
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=10.0)
        self.assertTrue(state.has_critical_alert)
        self.assertEqual(state.alerts["heater-heater_bed"].magnitude, 1.0)

    def test_heater_with_zero_target_is_not_flagged(self) -> None:
        state = PrinterState()
        state.set_temperature("heater_bed", actual=35.0, target=0.0, now=0.0)  # heater off, cooling down
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0)
        self.assertFalse(state.has_warning_alert)
        self.assertFalse(state.has_critical_alert)

    def test_target_change_suppresses_heating_alerts_while_progressing(self) -> None:
        state = PrinterState()
        state.set_temperature("extruder", actual=25.0, target=200.0, now=0.0)
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=0.0)
        self.assertNotIn("heater-extruder", state.alerts)

        state.set_temperature("extruder", actual=25.3, target=200.0, now=9.0)
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=9.0)
        self.assertNotIn("heater-extruder", state.alerts)

        state.set_temperature("extruder", actual=40.0, target=200.0, now=18.0)
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=18.0)
        self.assertNotIn("heater-extruder", state.alerts)

    def test_target_change_suppresses_cooling_alerts_while_progressing(self) -> None:
        state = PrinterState()
        state.set_temperature("extruder", actual=230.0, target=180.0, now=0.0)
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=0.0)
        self.assertNotIn("heater-extruder", state.alerts)

        state.set_temperature("extruder", actual=229.7, target=180.0, now=5.0)
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=5.0)
        self.assertNotIn("heater-extruder", state.alerts)

    def test_stalled_target_change_opens_gate_after_stall_window(self) -> None:
        state = PrinterState()
        state.set_temperature("extruder", actual=25.0, target=200.0, now=0.0)

        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=9.9)
        self.assertNotIn("heater-extruder", state.alerts)

        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=10.0)
        self.assertTrue(state.has_critical_alert)

    def test_small_temp_change_does_not_count_as_progress(self) -> None:
        state = PrinterState()
        state.set_temperature("extruder", actual=25.0, target=200.0, now=0.0)
        state.set_temperature("extruder", actual=25.1, target=200.0, now=5.0)

        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=10.1)
        self.assertTrue(state.has_critical_alert)

    def test_reaching_target_ends_gate_and_normal_alerting_resumes(self) -> None:
        state = PrinterState()
        state.set_temperature("extruder", actual=25.0, target=200.0, now=0.0)
        state.set_temperature("extruder", actual=200.0, target=200.0, now=4.0)
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=4.0)
        self.assertFalse(state.has_warning_alert)

        state.set_temperature("extruder", actual=170.0, target=200.0, now=5.0)
        state.evaluate_temperature_alerts(warning_c=5.0, critical_c=15.0, now=5.0)
        self.assertTrue(state.has_critical_alert)

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
