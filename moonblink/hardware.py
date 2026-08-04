"""Real Pimoroni Blinkt! hardware adapter.

Kept separate from the Null/fake drivers used in tests so that importing
this module (and only this module) requires the real ``blinkt`` package and
actual GPIO access. The import is performed lazily, inside ``__init__``, so
merely importing ``moonblink.hardware`` on non-Pi development/CI machines is
safe -- construction is what fails, loudly and immediately, per the
"fail fast" requirement for production runs.
"""

from __future__ import annotations


class BlinktHardwareError(RuntimeError):
    """Raised when the real Blinkt! hardware/library can't be initialized."""


class BlinktHardwareDriver:
    """:class:`~moonblink.animator.BlinktDriver` backed by the real ``blinkt`` package."""

    def __init__(self) -> None:
        try:
            import blinkt
        except Exception as exc:  # pragma: no cover - exercised via monkeypatched import failure
            raise BlinktHardwareError(
                "the 'blinkt' package is required to drive real hardware but could not be "
                "imported (are you running on a Raspberry Pi with Blinkt! attached, and is "
                "the 'blinkt' package installed?)"
            ) from exc

        try:
            blinkt.set_clear_on_exit(True)
        except Exception as exc:  # pragma: no cover - hardware-dependent failure
            raise BlinktHardwareError(f"failed to initialize Blinkt! hardware: {exc}") from exc

        self._blinkt = blinkt

    def set_pixel(self, index: int, red: int, green: int, blue: int, brightness: float) -> None:
        self._blinkt.set_pixel(index, red, green, blue, brightness)

    def show(self) -> None:
        self._blinkt.show()

    def clear(self) -> None:
        self._blinkt.clear()
        self._blinkt.show()
