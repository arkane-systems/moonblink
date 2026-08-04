from __future__ import annotations

import logging
import unittest

from moonblink.logging_setup import configure_logging


class ConfigureLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        # Reset level so other tests/processes aren't affected by whichever
        # level a given test case configures.
        configure_logging("INFO")

    def test_accepts_string_level_case_insensitively(self) -> None:
        configure_logging("debug")
        self.assertEqual(logging.getLogger("moonblink").level, logging.DEBUG)

    def test_accepts_int_level(self) -> None:
        configure_logging(logging.WARNING)
        self.assertEqual(logging.getLogger("moonblink").level, logging.WARNING)

    def test_rejects_invalid_level_name(self) -> None:
        with self.assertRaises(ValueError):
            configure_logging("not-a-real-level")

    def test_installs_exactly_one_handler_even_when_called_repeatedly(self) -> None:
        configure_logging("info")
        configure_logging("info")
        configure_logging("debug")
        handlers = logging.getLogger("moonblink").handlers
        self.assertEqual(len(handlers), 1)

    def test_child_logger_respects_configured_level(self) -> None:
        configure_logging("warning")
        child = logging.getLogger("moonblink.some_module")
        self.assertFalse(child.isEnabledFor(logging.INFO))
        self.assertTrue(child.isEnabledFor(logging.WARNING))


if __name__ == "__main__":
    unittest.main()
