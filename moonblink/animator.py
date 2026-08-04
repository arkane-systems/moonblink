"""Frame animator and Blinkt hardware adapter."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import time
from typing import Protocol

from .renderer import RenderedFrame


class BlinktDriver(Protocol):
    def set_pixel(self, index: int, red: int, green: int, blue: int, brightness: float) -> None: ...

    def show(self) -> None: ...

    def clear(self) -> None: ...


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend_pixel(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(_lerp(sa, ea, t))) for sa, ea in zip(start, end, strict=True))


@dataclass(slots=True)
class AnimationConfig:
    max_hz: float = 15.0
    transition_ms: int = 200
    brightness_cap: float = 0.35


class FrameAnimator:
    def __init__(self, driver: BlinktDriver, config: AnimationConfig | None = None) -> None:
        self._driver = driver
        self._config = config or AnimationConfig()
        self._last_emit = 0.0
        self._last_frame: RenderedFrame | None = None

    async def present(self, frame: RenderedFrame, now: float | None = None) -> bool:
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
