"""YAML configuration loading and validation for Moonblink.

Config files are optional to fully specify -- any section omitted falls
back to the defaults already baked into the render/animation/connector
dataclasses -- but anything that *is* present is validated strictly and
raises :class:`ConfigError` immediately on malformed input, per the
"fail fast on invalid files" requirement in AGENTS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time
from pathlib import Path
from typing import Any

import yaml

from .animator import AnimationConfig
from .connector import MoonrakerConfig
from .renderer import RenderConfig


class ConfigError(ValueError):
    """Raised when a Moonblink config file is missing, malformed, or invalid."""


_KNOWN_TOP_LEVEL_KEYS = {
    "moonraker",
    "api",
    "brightness_max",
    "update_rate_hz",
    "flash_duration_ms",
    "critical_alert_escalate_after_s",
    "colors",
    "temp_thresholds",
    "night_mode",
}

_KNOWN_COLOR_KEYS = {"printing", "idle", "paused", "error", "warning", "critical"}


@dataclass(slots=True)
class TempThresholds:
    warning_c: float = 5.0
    critical_c: float = 15.0


@dataclass(slots=True)
class NightMode:
    enabled: bool = False
    dim_to: float = 0.1
    start: time = time(22, 0)
    end: time = time(7, 0)

    def is_active(self, now: time) -> bool:
        """Return whether ``now`` falls within the (possibly midnight-wrapping) window."""
        if not self.enabled:
            return False
        if self.start <= self.end:
            return self.start <= now < self.end
        return now >= self.start or now < self.end


@dataclass(slots=True)
class MoonblinkConfig:
    moonraker: MoonrakerConfig = field(default_factory=MoonrakerConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    animation: AnimationConfig = field(default_factory=AnimationConfig)
    api_bind_address: str = "127.0.0.1"
    api_port: int = 8765
    temp_thresholds: TempThresholds = field(default_factory=TempThresholds)
    night_mode: NightMode = field(default_factory=NightMode)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"'{name}' must be a mapping, got {type(value).__name__}")
    return value


def _require_number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"'{name}' must be a number, got {value!r}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ConfigError(f"'{name}' must be >= {minimum}, got {number}")
    if maximum is not None and number > maximum:
        raise ConfigError(f"'{name}' must be <= {maximum}, got {number}")
    return number


def _require_color(value: Any, name: str) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ConfigError(f"color '{name}' must be a 3-element [r, g, b] list, got {value!r}")
    channels: list[int] = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int) or not (0 <= channel <= 255):
            raise ConfigError(f"color '{name}' channels must be integers 0-255, got {value!r}")
        channels.append(channel)
    return (channels[0], channels[1], channels[2])


def _parse_time(value: Any, name: str) -> time:
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        raise ConfigError(f"'{name}' must be a 'HH:MM' string, got {value!r}")
    parts = value.split(":")
    if len(parts) != 2:
        raise ConfigError(f"'{name}' must be in 'HH:MM' format, got {value!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        return time(hour, minute)
    except ValueError as exc:
        raise ConfigError(f"'{name}' must be a valid 'HH:MM' time, got {value!r}") from exc


def _load_yaml_document(raw_text: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse YAML: {exc}") from exc

    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigError(f"config root must be a mapping, got {type(document).__name__}")
    return document


def parse_config(document: dict[str, Any]) -> MoonblinkConfig:
    """Validate a parsed config mapping and produce a :class:`MoonblinkConfig`."""
    unknown = set(document) - _KNOWN_TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"unknown config key(s): {', '.join(sorted(unknown))}")

    moonraker_config = MoonrakerConfig()
    if "moonraker" in document:
        section = _require_mapping(document["moonraker"], "moonraker")
        unknown_moonraker = set(section) - {"url", "rest_url", "poll_interval", "reconnect_delay", "max_reconnect_delay"}
        if unknown_moonraker:
            raise ConfigError(f"unknown moonraker config key(s): {', '.join(sorted(unknown_moonraker))}")
        websocket_url = section.get("url", moonraker_config.websocket_url)
        rest_url = section.get("rest_url", moonraker_config.rest_url)
        if not isinstance(websocket_url, str) or not websocket_url:
            raise ConfigError("'moonraker.url' must be a non-empty string")
        if not isinstance(rest_url, str) or not rest_url:
            raise ConfigError("'moonraker.rest_url' must be a non-empty string")
        moonraker_config = MoonrakerConfig(
            websocket_url=websocket_url,
            rest_url=rest_url,
            poll_interval=_require_number(section.get("poll_interval", moonraker_config.poll_interval), "moonraker.poll_interval", minimum=0.1),
            reconnect_delay=_require_number(section.get("reconnect_delay", moonraker_config.reconnect_delay), "moonraker.reconnect_delay", minimum=0.0),
            max_reconnect_delay=_require_number(
                section.get("max_reconnect_delay", moonraker_config.max_reconnect_delay), "moonraker.max_reconnect_delay", minimum=0.0
            ),
        )

    api_bind_address = "127.0.0.1"
    api_port = 8765
    if "api" in document:
        section = _require_mapping(document["api"], "api")
        unknown_api = set(section) - {"bind_address", "port"}
        if unknown_api:
            raise ConfigError(f"unknown api config key(s): {', '.join(sorted(unknown_api))}")
        api_bind_address = section.get("bind_address", api_bind_address)
        if not isinstance(api_bind_address, str) or not api_bind_address:
            raise ConfigError("'api.bind_address' must be a non-empty string")
        api_port = int(_require_number(section.get("port", api_port), "api.port", minimum=1, maximum=65535))

    render_defaults = RenderConfig()
    brightness_max = _require_number(document.get("brightness_max", render_defaults.brightness_max), "brightness_max", minimum=0.0, maximum=1.0)
    update_rate_hz = _require_number(document.get("update_rate_hz", render_defaults.update_rate_hz), "update_rate_hz", minimum=1.0, maximum=20.0)
    flash_duration_ms = int(
        _require_number(document.get("flash_duration_ms", render_defaults.flash_duration_ms), "flash_duration_ms", minimum=0.0)
    )
    escalate_after_s = _require_number(
        document.get("critical_alert_escalate_after_s", render_defaults.critical_alert_escalate_after_s),
        "critical_alert_escalate_after_s",
        minimum=0.0,
    )

    colors = document.get("colors", {})
    if colors:
        colors = _require_mapping(colors, "colors")
        unknown_colors = set(colors) - _KNOWN_COLOR_KEYS
        if unknown_colors:
            raise ConfigError(f"unknown color key(s): {', '.join(sorted(unknown_colors))}")

    def _color(key: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
        if key not in colors:
            return default
        return _require_color(colors[key], key)

    render_config = RenderConfig(
        printing_color=_color("printing", render_defaults.printing_color),
        idle_color=_color("idle", render_defaults.idle_color),
        paused_color=_color("paused", render_defaults.paused_color),
        error_color=_color("error", render_defaults.error_color),
        warning_color=_color("warning", render_defaults.warning_color),
        critical_color=_color("critical", render_defaults.critical_color),
        brightness_max=brightness_max,
        flash_duration_ms=flash_duration_ms,
        update_rate_hz=int(update_rate_hz),
        critical_alert_escalate_after_s=escalate_after_s,
    )

    animation_config = AnimationConfig(
        max_hz=update_rate_hz,
        transition_ms=AnimationConfig().transition_ms,
        brightness_cap=brightness_max,
    )

    temp_thresholds = TempThresholds()
    if "temp_thresholds" in document:
        section = _require_mapping(document["temp_thresholds"], "temp_thresholds")
        unknown_temp = set(section) - {"warning_c", "critical_c"}
        if unknown_temp:
            raise ConfigError(f"unknown temp_thresholds key(s): {', '.join(sorted(unknown_temp))}")
        warning_c = _require_number(section.get("warning_c", temp_thresholds.warning_c), "temp_thresholds.warning_c", minimum=0.0)
        critical_c = _require_number(section.get("critical_c", temp_thresholds.critical_c), "temp_thresholds.critical_c", minimum=0.0)
        if critical_c < warning_c:
            raise ConfigError("'temp_thresholds.critical_c' must be >= 'temp_thresholds.warning_c'")
        temp_thresholds = TempThresholds(warning_c=warning_c, critical_c=critical_c)

    night_mode = NightMode()
    if "night_mode" in document:
        section = _require_mapping(document["night_mode"], "night_mode")
        unknown_night = set(section) - {"enabled", "dim_to", "start", "end"}
        if unknown_night:
            raise ConfigError(f"unknown night_mode key(s): {', '.join(sorted(unknown_night))}")
        enabled = section.get("enabled", night_mode.enabled)
        if not isinstance(enabled, bool):
            raise ConfigError("'night_mode.enabled' must be a boolean")
        dim_to = _require_number(section.get("dim_to", night_mode.dim_to), "night_mode.dim_to", minimum=0.0, maximum=1.0)
        start = _parse_time(section.get("start", night_mode.start), "night_mode.start")
        end = _parse_time(section.get("end", night_mode.end), "night_mode.end")
        night_mode = NightMode(enabled=enabled, dim_to=dim_to, start=start, end=end)

    return MoonblinkConfig(
        moonraker=moonraker_config,
        render=render_config,
        animation=animation_config,
        api_bind_address=api_bind_address,
        api_port=api_port,
        temp_thresholds=temp_thresholds,
        night_mode=night_mode,
    )


def load_config(path: str | Path) -> MoonblinkConfig:
    """Load, parse, and validate a Moonblink YAML config file.

    Raises :class:`ConfigError` if the file is missing, unreadable, not
    valid YAML, or fails validation.
    """
    file_path = Path(path)
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read config file '{file_path}': {exc}") from exc

    document = _load_yaml_document(raw_text)
    return parse_config(document)


def effective_render_config(render_config: RenderConfig, night_mode: NightMode, now_time: time | None = None) -> RenderConfig:
    """Return ``render_config`` with brightness dimmed if inside the night-mode window.

    Kept as a pure function of its inputs (no ambient clock reads beyond
    the optional ``now_time`` override) so it composes cleanly with the
    otherwise-pure renderer -- callers pass the current wall-clock time in
    explicitly.
    """
    now_time = datetime.now().time() if now_time is None else now_time  # noqa: DTZ005 - local wall-clock time is intentional for night mode
    if not night_mode.is_active(now_time):
        return render_config
    return replace(render_config, brightness_max=min(render_config.brightness_max, night_mode.dim_to))
