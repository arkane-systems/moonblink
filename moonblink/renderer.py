"""Pure renderer from printer state to 8-pixel frames."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

from .state import (
    PRINTER_ERROR,
    PRINTER_IDLE,
    PRINTER_PAUSED,
    PRINTER_PRINTING,
    PrinterState,
    RGB,
)


BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)
AMBER: RGB = (255, 160, 0)
CYAN: RGB = (0, 255, 255)
MAGENTA: RGB = (255, 0, 255)


@dataclass(slots=True)
class RenderConfig:
    printing_color: RGB = (0, 255, 0)
    idle_color: RGB = (0, 0, 255)
    paused_color: RGB = (255, 255, 0)
    error_color: RGB = (255, 0, 0)
    warning_color: RGB = AMBER
    critical_color: RGB = (255, 0, 0)
    brightness_max: float = 0.35
    flash_duration_ms: int = 300
    update_rate_hz: int = 15
    disable_layer_flash: bool = False
    progress_start_color: RGB = CYAN
    progress_end_color: RGB = MAGENTA


@dataclass(slots=True)
class RenderedFrame:
    pixels: tuple[RGB, ...]
    brightness: float
    mode: str


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend_color(start: RGB, end: RGB, t: float) -> RGB:
    t = _clamp(t)
    return tuple(int(round(_lerp(sa, ea, t))) for sa, ea in zip(start, end, strict=True))


def _scale_color(color: RGB, factor: float) -> RGB:
    factor = _clamp(factor)
    return tuple(int(round(channel * factor)) for channel in color)


def _pulse(now: float, period: float = 1.2, minimum: float = 0.25, maximum: float = 1.0) -> float:
    phase = (now % period) / period
    wave = 0.5 - 0.5 * math.cos(phase * math.tau)
    return _lerp(minimum, maximum, wave)


def _spark_index(now: float, width: int = 6, speed: float = 2.0) -> int:
    return int(now * speed) % max(1, width)


def render_frame(state: PrinterState, config: RenderConfig, now: float | None = None) -> RenderedFrame:
    now = time.monotonic() if now is None else now

    if state.printer_mode == PRINTER_ERROR or state.has_critical_alert:
        pulse = _pulse(now, period=0.4, minimum=0.55, maximum=1.0)
        pixels = tuple(_scale_color(config.critical_color, pulse) for _ in range(8))
        return RenderedFrame(pixels=pixels, brightness=config.brightness_max, mode="critical")

    if state.flash_until > now and not config.disable_layer_flash:
        remaining = max(0.0, state.flash_until - now)
        pulse = _clamp(remaining / max(config.flash_duration_ms / 1000.0, 0.001))
        pixels = tuple(_scale_color(WHITE, pulse) for _ in range(8))
        return RenderedFrame(pixels=pixels, brightness=config.brightness_max, mode="flash")

    if state.user_effect.active(now):
        if state.user_effect.kind == "pause":
            color = config.paused_color
        elif state.user_effect.kind == "resume":
            color = config.printing_color
        elif state.user_effect.kind == "ack":
            color = (80, 80, 80)
        else:
            color = WHITE
        pixels = tuple(_scale_color(color, _pulse(now, period=0.8, minimum=0.2, maximum=1.0)) for _ in range(8))
        return RenderedFrame(pixels=pixels, brightness=config.brightness_max, mode="user-effect")

    pixels = [BLACK for _ in range(8)]
    mode = state.printer_mode

    if state.printer_mode == PRINTER_PRINTING:
        pixels[0] = config.printing_color
        fill = _clamp(state.progress) * 6.0
        whole = int(fill)
        fractional = fill - whole
        for index in range(6):
            if index < whole:
                t = index / 5 if 5 else 0.0
                pixels[index + 1] = _blend_color(config.progress_start_color, config.progress_end_color, t)
            elif index == whole and fractional > 0:
                base = _blend_color(config.progress_start_color, config.progress_end_color, min(1.0, fill / 6.0))
                pixels[index + 1] = _scale_color(base, max(0.15, fractional))
        if state.motion_active:
            spark = 1 + _spark_index(now, width=6)
            pixels[spark] = _scale_color(WHITE, 0.9)

    elif state.printer_mode == PRINTER_PAUSED:
        pixels[0] = config.paused_color
        fill = int(round(_clamp(state.progress) * 6.0))
        for index in range(fill):
            pixels[index + 1] = _blend_color(config.progress_start_color, config.progress_end_color, index / 5 if 5 else 0.0)
    elif state.printer_mode == PRINTER_IDLE:
        pixels[0] = config.idle_color
        breathe = _pulse(now, period=3.0, minimum=0.08, maximum=0.22)
        for index in range(1, 7):
            pixels[index] = _scale_color(config.idle_color, breathe * (0.7 if index % 2 else 0.4))
    else:
        pixels[0] = config.error_color if state.printer_mode == PRINTER_ERROR else config.idle_color

    if state.has_warning_alert:
        pulse = _pulse(now, period=1.6, minimum=0.15, maximum=1.0)
        pixels[7] = _scale_color(config.warning_color, pulse)

    return RenderedFrame(pixels=tuple(pixels), brightness=config.brightness_max, mode=mode)
