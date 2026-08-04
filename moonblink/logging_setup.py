"""Logging configuration for systemd/journald-friendly console output.

When Moonblink runs as a systemd service, stdout/stderr are captured by
journald, which already timestamps and tags every line -- so our own log
records should skip the timestamp and just carry level + logger name +
message. Configuring the ``moonblink`` logger (rather than the process-wide
root logger) keeps this scoped to our own output, so embedding tools/tests
that configure logging themselves aren't clobbered.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str | int = "INFO") -> None:
    """Configure the ``moonblink`` logger hierarchy for console/journald output.

    Safe to call more than once (e.g. from tests) -- only the first call
    installs a handler; subsequent calls just adjust the effective level.
    """
    global _CONFIGURED

    if isinstance(level, str):
        resolved = logging.getLevelName(level.upper())
        if not isinstance(resolved, int):
            # ValueError (not TypeError) is intentional: an unrecognized level
            # *name* is invalid data, not a wrong argument type -- callers
            # (including our own CLI argument parsing) expect ValueError here.
            raise ValueError(f"invalid log level: {level!r}")  # noqa: TRY004
        level = resolved

    logger = logging.getLogger("moonblink")
    logger.setLevel(level)

    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        # No timestamp: systemd/journald already prefixes each line with one.
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        _CONFIGURED = True
