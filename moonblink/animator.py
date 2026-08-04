"""Frame animator and Blinkt hardware adapter."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from .renderer import RenderedFrame

logger = logging.getLogger(__name__)


class BlinktDriver(Protocol):
    def set_pixel(self, index: int, red: int, green: int, blue: int, brightness: float) -> None: ...

    def show(self) -> None: ...

    def clear(self) -> None: ...


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend_pixel(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(_lerp(sa, ea, t)) for sa, ea in zip(start, end, strict=True))


@dataclass(slots=True)
class AnimationConfig:
    max_hz: float = 15.0
    transition_ms: int = 200
    brightness_cap: float = 0.35


class FrameAnimator:
    def __init__(self, driver: BlinktDriver, config: AnimationConfig | None = None, *, log: logging.Logger | None = None) -> None:
        self._driver = driver
        self._config = config or AnimationConfig()
        self._last_emit = 0.0
        self._last_frame: RenderedFrame | None = None
        self._log = log or logger
        self._last_logged_mode: str | None = None

    @property
    def max_hz(self) -> float:
        return self._config.max_hz

    async def present(self, frame: RenderedFrame, now: float | None = None) -> bool:
        if frame.mode != self._last_logged_mode:
            self._last_logged_mode = frame.mode
            # One INFO line per rendering *mode* transition (printing, idle,
            # paused, warning, critical, error, ...) -- not per frame, since
            # several modes (e.g. idle's breathing effect) vary color/
            # brightness continuously every frame. This is the human-
            # readable "what is moonblink doing" narration for the console/
            # journal; ConsoleEchoDriver's per-write DEBUG log is the lower-
            # level complement showing the exact pixel values sent to
            # hardware.
            self._log.info("frame: mode -> %s (brightness=%.2f)", frame.mode, frame.brightness)

        now = time.monotonic() if now is None else now
        interval = 1.0 / max(self._config.max_hz, 0.1)
        if self._last_frame is not None and now - self._last_emit < interval:
            return False

        previous = self._last_frame
        self._last_frame = frame
        self._last_emit = now

        if previous is None or self._config.transition_ms <= 0:
            self._write_frame(frame)
            return True

        steps = max(1, min(6, self._config.transition_ms // 40))
        for index in range(1, steps + 1):
            t = index / steps
            blended = RenderedFrame(
                pixels=tuple(_blend_pixel(start, end, t) for start, end in zip(previous.pixels, frame.pixels, strict=True)),
                brightness=_lerp(previous.brightness, frame.brightness, t),
                mode=frame.mode,
            )
            self._write_frame(blended)
            if index < steps:
                await asyncio.sleep(self._config.transition_ms / 1000.0 / steps)
        return True

    def clear(self) -> None:
        self._driver.clear()

    def _write_frame(self, frame: RenderedFrame) -> None:
        brightness = _clamp(min(frame.brightness, self._config.brightness_cap))
        for index, (red, green, blue) in enumerate(frame.pixels):
            self._driver.set_pixel(index, red, green, blue, brightness)
        self._driver.show()


class NullBlinktDriver:
    def set_pixel(self, index: int, red: int, green: int, blue: int, brightness: float) -> None:
        return

    def show(self) -> None:
        return

    def clear(self) -> None:
        return


class ConsoleEchoDriver:
    """Wraps another :class:`BlinktDriver`, logging the resulting frame whenever it changes.

    Used by ``--simulate`` so LED behaviour stays visible over SSH/journalctl
    regardless of whether real Blinkt! hardware is attached -- this both lets
    the console double-check real hardware output, and is the only feedback
    available at all when no hardware is present.
    """

    def __init__(self, inner: BlinktDriver, *, log: logging.Logger | None = None) -> None:
        self._inner = inner
        self._log = log or logger
        self._pixels: list[tuple[int, int, int, float]] = [(0, 0, 0, 0.0)] * 8
        self._last_logged: tuple[tuple[int, int, int, float], ...] | None = None

    def set_pixel(self, index: int, red: int, green: int, blue: int, brightness: float) -> None:
        self._pixels[index] = (red, green, blue, brightness)
        self._inner.set_pixel(index, red, green, blue, brightness)

    def show(self) -> None:
        self._inner.show()
        state = tuple(self._pixels)
        if state != self._last_logged:
            self._last_logged = state
            # DEBUG, not INFO: this fires once per hardware write, including
            # every intermediate step of a brightness/color transition, so
            # it's too noisy for the default console view -- use --log-level
            # debug to see it. FrameAnimator.present() logs one INFO line
            # per *target* frame change instead, which is what --simulate's
            # console narration relies on.
            self._log.debug("blinkt write: %s", _format_pixels(state))

    def clear(self) -> None:
        self._inner.clear()
        self._pixels = [(0, 0, 0, 0.0)] * 8
        if self._last_logged is not None:
            self._last_logged = None
            self._log.debug("blinkt write: cleared")


def _format_pixels(pixels: tuple[tuple[int, int, int, float], ...]) -> str:
    return " ".join(f"{index}=#{red:02x}{green:02x}{blue:02x}@{brightness:.2f}" for index, (red, green, blue, brightness) in enumerate(pixels))
