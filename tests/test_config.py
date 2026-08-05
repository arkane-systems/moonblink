from __future__ import annotations

import unittest
from datetime import time

from moonblink.config import ConfigError, NightMode, parse_config


class ConfigParsingTests(unittest.TestCase):
    def test_empty_document_uses_defaults(self) -> None:
        config = parse_config({})
        self.assertEqual(config.api_bind_address, "127.0.0.1")
        self.assertEqual(config.api_port, 8765)
        self.assertEqual(config.render.brightness_max, 0.35)
        self.assertTrue(config.render.calm_when_idle)
        self.assertFalse(config.night_mode.enabled)

    def test_full_valid_document_is_parsed(self) -> None:
        document = {
            "moonraker": {"url": "ws://printer/websocket", "rest_url": "http://printer"},
            "api": {"bind_address": "127.0.0.1", "port": 9000},
            "brightness_max": 0.5,
            "update_rate_hz": 10,
            "flash_duration_ms": 250,
            "calm_when_idle": False,
            "reverse_progress_fill": True,
            "critical_alert_escalate_after_s": 45,
            "colors": {"printing": [1, 2, 3]},
            "temp_thresholds": {"warning_c": 4, "critical_c": 12, "progress_min_change_c": 0.3, "progress_stall_s": 12},
            "night_mode": {"enabled": True, "dim_to": 0.05, "start": "23:00", "end": "06:30"},
        }
        config = parse_config(document)
        self.assertEqual(config.moonraker.websocket_url, "ws://printer/websocket")
        self.assertEqual(config.api_port, 9000)
        self.assertEqual(config.render.brightness_max, 0.5)
        self.assertFalse(config.render.calm_when_idle)
        self.assertTrue(config.render.reverse_progress_fill)
        self.assertEqual(config.render.printing_color, (1, 2, 3))
        self.assertEqual(config.render.critical_alert_escalate_after_s, 45)
        self.assertEqual(config.temp_thresholds.warning_c, 4)
        self.assertEqual(config.temp_thresholds.critical_c, 12)
        self.assertEqual(config.temp_thresholds.progress_min_change_c, 0.3)
        self.assertEqual(config.temp_thresholds.progress_stall_s, 12)
        self.assertTrue(config.night_mode.enabled)
        self.assertEqual(config.night_mode.start, time(23, 0))
        self.assertEqual(config.night_mode.end, time(6, 30))

    def test_unknown_top_level_key_raises(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"totally_unknown_key": True})

    def test_brightness_out_of_range_raises(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"brightness_max": 1.5})

    def test_invalid_color_raises(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"colors": {"printing": [1, 2, 300]}})

    def test_invalid_night_mode_time_raises(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"night_mode": {"start": "not-a-time"}})

    def test_reverse_progress_fill_must_be_boolean(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"reverse_progress_fill": "yes"})

    def test_calm_when_idle_must_be_boolean(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"calm_when_idle": "no"})

    def test_critical_below_warning_threshold_raises(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"temp_thresholds": {"warning_c": 20, "critical_c": 5}})

    def test_non_mapping_document_raises(self) -> None:
        with self.assertRaises(ConfigError):
            parse_config({"moonraker": "not-a-mapping"})

    def test_load_config_missing_file_raises(self) -> None:
        from moonblink.config import load_config

        with self.assertRaises(ConfigError):
            load_config("/nonexistent/path/moonblink.yaml")

    def test_load_config_reads_repo_default(self) -> None:
        from pathlib import Path

        from moonblink.config import load_config

        repo_root = Path(__file__).resolve().parent.parent
        config = load_config(repo_root / "config" / "moonblink.yaml")
        self.assertEqual(config.render.printing_color, (0, 255, 0))
        self.assertTrue(isinstance(config.night_mode.start, time))


class EffectiveRenderConfigTests(unittest.TestCase):
    def test_dims_brightness_inside_night_window(self) -> None:
        from moonblink.config import effective_render_config
        from moonblink.renderer import RenderConfig

        night_mode = NightMode(enabled=True, dim_to=0.05, start=time(22, 0), end=time(7, 0))
        base = RenderConfig(brightness_max=0.35)

        dimmed = effective_render_config(base, night_mode, now_time=time(23, 30))
        self.assertEqual(dimmed.brightness_max, 0.05)

        unaffected = effective_render_config(base, night_mode, now_time=time(12, 0))
        self.assertEqual(unaffected.brightness_max, 0.35)


class NightModeWindowTests(unittest.TestCase):
    def test_simple_window(self) -> None:
        night_mode = NightMode(enabled=True, start=time(22, 0), end=time(23, 0))
        self.assertTrue(night_mode.is_active(time(22, 30)))
        self.assertFalse(night_mode.is_active(time(21, 0)))

    def test_midnight_wrapping_window(self) -> None:
        night_mode = NightMode(enabled=True, start=time(22, 0), end=time(7, 0))
        self.assertTrue(night_mode.is_active(time(23, 0)))
        self.assertTrue(night_mode.is_active(time(2, 0)))
        self.assertFalse(night_mode.is_active(time(12, 0)))

    def test_disabled_is_never_active(self) -> None:
        night_mode = NightMode(enabled=False, start=time(22, 0), end=time(7, 0))
        self.assertFalse(night_mode.is_active(time(23, 0)))


if __name__ == "__main__":
    unittest.main()
