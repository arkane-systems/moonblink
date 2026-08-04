"""Printer state model for Moonblink.

The renderer consumes a normalized, hardware-agnostic snapshot so tests can
exercise the LED logic without needing Moonraker or Blinkt hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


PrinterMode = str
AlertSeverity = str
RGB = tuple[int, int, int]

PRINTER_IDLE = "idle"
PRINTER_PRINTING = "printing"
PRINTER_PAUSED = "paused"
PRINTER_ERROR = "error"

ALERT_WARNING = "warning"
ALERT_CRITICAL = "critical"

USER_EFFECT_NONE = "none"
USER_EFFECT_ACK = "ack"
USER_EFFECT_PAUSE = "pause"
USER_EFFECT_RESUME = "resume"


@dataclass(slots=True)
class TemperatureReading:
    actual: float | None = None
    target: float | None = None


@dataclass(slots=True)
class Alert:
    alert_id: str
    kind: str
    severity: AlertSeverity
    message: str = ""
    acknowledged: bool = False
    active: bool = True
    created_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class UserEffect:
    kind: str = USER_EFFECT_NONE
    expires_at: float = 0.0

    def active(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.kind != USER_EFFECT_NONE and self.expires_at > now


@dataclass(slots=True)
class PrinterState:
    printer_mode: PrinterMode = PRINTER_IDLE
    progress: float = 0.0
    elapsed: float | None = None
    remaining: float | None = None
    temperatures: dict[str, TemperatureReading] = field(default_factory=dict)
    motion_active: bool = False
    motion_velocity: float = 0.0
    last_layer: int | None = None
    alerts: dict[str, Alert] = field(default_factory=dict)
    flash_until: float = 0.0
    user_effect: UserEffect = field(default_factory=UserEffect)

    def set_printer_mode(self, mode: str) -> None:
        self.printer_mode = mode or PRINTER_IDLE

    def set_progress(self, progress: float | None, elapsed: float | None = None, remaining: float | None = None) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        self.elapsed = elapsed
        self.remaining = remaining

    def set_temperature(self, name: str, actual: float | None = None, target: float | None = None) -> None:
        self.temperatures[name] = TemperatureReading(actual=actual, target=target)

    def set_motion(self, active: bool, velocity: float | None = None) -> None:
        self.motion_active = active
        if velocity is not None:
            self.motion_velocity = float(velocity)

    def set_layer_change(self, layer: int | None, *, now: float | None = None, flash_duration: float = 0.3) -> None:
        self.last_layer = layer
        now = time.monotonic() if now is None else now
        self.flash_until = max(self.flash_until, now + flash_duration)

    def add_alert(
        self,
        alert_id: str,
        *,
        kind: str,
        severity: AlertSeverity,
        message: str = "",
    ) -> None:
        self.alerts[alert_id] = Alert(
            alert_id=alert_id,
            kind=kind,
            severity=severity,
            message=message,
        )

    def acknowledge_alert(self, alert_id: str) -> None:
        alert = self.alerts.get(alert_id)
        if alert is not None:
            alert.acknowledged = True
            alert.active = False

    def clear_alert(self, alert_id: str) -> None:
        self.alerts.pop(alert_id, None)

    def clear_all_alerts(self) -> None:
        self.alerts.clear()

    def set_user_effect(self, kind: str, *, duration: float = 0.5, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.user_effect = UserEffect(kind=kind, expires_at=now + duration)

    @property
    def has_critical_alert(self) -> bool:
        return any(alert.active and not alert.acknowledged and alert.severity == ALERT_CRITICAL for alert in self.alerts.values())

    @property
    def has_warning_alert(self) -> bool:
        return any(alert.active and not alert.acknowledged and alert.severity == ALERT_WARNING for alert in self.alerts.values())

    @property
    def active_alerts(self) -> list[Alert]:
        return [alert for alert in self.alerts.values() if alert.active and not alert.acknowledged]

    def update_from_status(self, payload: dict[str, Any]) -> None:
        state = payload.get("state") or payload.get("printer_state") or payload.get("status")
        if isinstance(state, str):
            self.set_printer_mode(state.lower())

        progress = payload.get("progress")
        if progress is None:
            stats = payload.get("print_stats")
            if isinstance(stats, dict):
                progress = stats.get("progress")
                if stats.get("state"):
                    self.set_printer_mode(str(stats["state"]).lower())
                self.set_progress(progress, elapsed=stats.get("print_duration"), remaining=stats.get("remaining"))
                return

        self.set_progress(progress, elapsed=payload.get("elapsed"), remaining=payload.get("remaining"))

    def update_from_temperature(self, payload: dict[str, Any]) -> None:
        for name, value in payload.items():
            if isinstance(value, dict):
                self.set_temperature(
                    name,
                    actual=value.get("actual") or value.get("temp") or value.get("temperature"),
                    target=value.get("target"),
                )

    def update_from_motion(self, payload: dict[str, Any]) -> None:
        self.set_motion(
            bool(payload.get("active", True)),
            velocity=payload.get("velocity") or payload.get("speed"),
        )

    def update_from_layer_change(self, payload: dict[str, Any], *, now: float | None = None, flash_duration: float = 0.3) -> None:
        layer = payload.get("layer")
        if isinstance(layer, int):
            self.set_layer_change(layer, now=now, flash_duration=flash_duration)
            return
        if layer is None:
            self.set_layer_change(None, now=now, flash_duration=flash_duration)

    def update_from_gcode_response(self, response: str) -> None:
        normalized = response.lower()
        if "error" in normalized or "fail" in normalized:
            self.add_alert(
                "gcode-response",
                kind="gcode",
                severity=ALERT_CRITICAL if "fatal" in normalized or "shutdown" in normalized else ALERT_WARNING,
                message=response,
            )
