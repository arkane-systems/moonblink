"""Printer state model for Moonblink.

The renderer consumes a normalized, hardware-agnostic snapshot so tests can
exercise the LED logic without needing Moonraker or Blinkt hardware.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
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

# Klipper's real `print_stats.state` values (see
# https://www.klipper3d.org/Status_Reference.html) don't line up 1:1 with
# our internal PRINTER_* modes -- "standby"/"complete"/"cancelled" all mean
# "nothing is actively printing", i.e. our PRINTER_IDLE.
_PRINTER_MODE_ALIASES = {
    "standby": PRINTER_IDLE,
    "complete": PRINTER_IDLE,
    "cancelled": PRINTER_IDLE,
}


def normalize_printer_mode(raw: str) -> str:
    """Map a raw Klipper ``print_stats.state`` value onto our PRINTER_* modes."""
    mode = raw.lower()
    return _PRINTER_MODE_ALIASES.get(mode, mode)


@dataclass(slots=True)
class TemperatureReading:
    actual: float | None = None
    target: float | None = None
    target_changed_at: float | None = None
    last_progress_at: float | None = None
    last_actual_for_progress: float | None = None


@dataclass(slots=True)
class Alert:
    alert_id: str
    kind: str
    severity: AlertSeverity
    message: str = ""
    acknowledged: bool = False
    active: bool = True
    created_at: float = field(default_factory=time.monotonic)
    # Normalized 0..1 magnitude (e.g. how far a temperature is off-target
    # relative to the critical threshold) used by the renderer to scale
    # indicator brightness. 0 means "just crossed into alert", 1 means
    # "at or beyond the critical threshold".
    magnitude: float = 0.0


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

    def set_printer_mode(self, mode: str, *, now: float | None = None) -> None:
        mode = mode or PRINTER_IDLE
        previous = self.printer_mode
        if mode != previous:
            # Spec priority 6 ("user interactions") calls for a short pulse
            # whenever a print is paused or resumed -- and that should hold
            # regardless of *who* triggered the pause/resume (physical
            # button, Mainsail/Fluidd, or our own control API), so it's
            # detected here from the raw mode transition rather than
            # requiring every caller to remember to call set_user_effect.
            if previous == PRINTER_PRINTING and mode == PRINTER_PAUSED:
                self.set_user_effect(USER_EFFECT_PAUSE, now=now)
            elif previous == PRINTER_PAUSED and mode == PRINTER_PRINTING:
                self.set_user_effect(USER_EFFECT_RESUME, now=now)
        self.printer_mode = mode

    def set_progress(self, progress: float | None, elapsed: float | None = None, remaining: float | None = None) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        self.elapsed = elapsed
        self.remaining = remaining

    def set_temperature(self, name: str, actual: float | None = None, target: float | None = None, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        previous = self.temperatures.get(name)

        # A heater only participates in alerting/progress tracking while it
        # has a positive target.
        active_target = target is not None and target > 0

        if previous is None:
            self.temperatures[name] = TemperatureReading(
                actual=actual,
                target=target,
                target_changed_at=now if active_target else None,
                last_progress_at=now if active_target and actual is not None else None,
                last_actual_for_progress=actual if active_target else None,
            )
            return

        target_changed = previous.target != target
        if not active_target:
            self.temperatures[name] = TemperatureReading(actual=actual, target=target)
            return

        if target_changed:
            self.temperatures[name] = TemperatureReading(
                actual=actual,
                target=target,
                target_changed_at=now,
                last_progress_at=now if actual is not None else None,
                last_actual_for_progress=actual,
            )
            return

        self.temperatures[name] = TemperatureReading(
            actual=actual,
            target=target,
            target_changed_at=previous.target_changed_at,
            last_progress_at=previous.last_progress_at,
            last_actual_for_progress=previous.last_actual_for_progress,
        )

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
        now: float | None = None,
    ) -> None:
        existing = self.alerts.get(alert_id)
        if existing is not None:
            # Refresh an already-outstanding alert in place so its
            # `created_at` (used for critical-escalation timing) and any
            # user acknowledgement are preserved across repeated updates
            # for the same still-ongoing condition.
            existing.kind = kind
            existing.severity = severity
            existing.message = message
            existing.active = True
            return

        self.alerts[alert_id] = Alert(
            alert_id=alert_id,
            kind=kind,
            severity=severity,
            message=message,
            created_at=time.monotonic() if now is None else now,
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

    @property
    def active_critical_alerts(self) -> list[Alert]:
        return [alert for alert in self.active_alerts if alert.severity == ALERT_CRITICAL]

    def oldest_critical_alert_age(self, now: float | None = None) -> float | None:
        """Seconds since the longest-outstanding unacknowledged critical alert was raised."""
        active = self.active_critical_alerts
        if not active:
            return None
        now = time.monotonic() if now is None else now
        oldest_created_at = min(alert.created_at for alert in active)
        return max(0.0, now - oldest_created_at)

    def indicator_magnitude(self) -> float:
        """Peak normalized magnitude across all active, unacknowledged alerts."""
        active = self.active_alerts
        if not active:
            return 0.0
        return max(alert.magnitude for alert in active)

    def evaluate_temperature_alerts(
        self,
        *,
        warning_c: float,
        critical_c: float,
        temp_progress_min_change_c: float = 0.2,
        temp_progress_stall_s: float = 10.0,
        now: float | None = None,
    ) -> None:
        """Raise or clear ``heater-<name>`` alerts from recorded temperature readings.

        A heater is only evaluated when it has a positive target (i.e. it is
        actively being heated) -- an idle/off heater cooling toward ambient
        should not be flagged as "off-target".
        """
        now = time.monotonic() if now is None else now

        for name, reading in self.temperatures.items():
            alert_id = f"heater-{name}"
            if reading.actual is None or reading.target is None or reading.target <= 0:
                self.clear_alert(alert_id)
                reading.target_changed_at = None
                reading.last_progress_at = None
                reading.last_actual_for_progress = None
                continue

            # After any target change, suppress alerts while the reading is
            # still moving toward the target. If movement stalls long enough,
            # reopen normal warning/critical threshold evaluation.
            if reading.target_changed_at is not None:
                min_progress = max(0.0, temp_progress_min_change_c)
                reached_target = abs(reading.actual - reading.target) <= min_progress
                if reached_target:
                    self.clear_alert(alert_id)
                    reading.target_changed_at = None
                    reading.last_progress_at = now
                    reading.last_actual_for_progress = reading.actual
                    continue

                if reading.last_actual_for_progress is None:
                    reading.last_actual_for_progress = reading.actual
                else:
                    progress_toward_target = abs(reading.last_actual_for_progress - reading.target) - abs(reading.actual - reading.target)
                    if progress_toward_target >= min_progress:
                        reading.last_progress_at = now
                        reading.last_actual_for_progress = reading.actual
                        self.clear_alert(alert_id)
                        continue

                baseline = reading.last_progress_at if reading.last_progress_at is not None else reading.target_changed_at
                stalled_for = max(0.0, now - baseline)
                if stalled_for < max(0.0, temp_progress_stall_s):
                    self.clear_alert(alert_id)
                    continue

                # Gate expired: resume normal threshold alerts for this target.
                reading.target_changed_at = None

            delta = abs(reading.actual - reading.target)
            if critical_c > 0:
                magnitude = max(0.0, min(1.0, delta / critical_c))
            else:
                magnitude = 1.0 if delta > 0 else 0.0

            if delta >= critical_c:
                self.add_alert(alert_id, kind="heater", severity=ALERT_CRITICAL, message=f"{name} off-target by {delta:.1f}C", now=now)
                self.alerts[alert_id].magnitude = magnitude
            elif delta >= warning_c:
                self.add_alert(alert_id, kind="heater", severity=ALERT_WARNING, message=f"{name} off-target by {delta:.1f}C", now=now)
                self.alerts[alert_id].magnitude = magnitude
            else:
                self.clear_alert(alert_id)

    def update_from_status(self, payload: dict[str, Any], *, now: float | None = None) -> None:
        """Apply a Moonraker printer-object status payload.

        ``payload`` is the raw ``{object_name: {field: value, ...}, ...}``
        mapping Moonraker uses both for ``notify_status_update`` websocket
        notifications (``params[0]``) and for
        ``GET /printer/objects/query`` REST responses (``result.status``),
        so this single method is the one true translation of "what did
        Moonraker just tell us" into our normalized state, regardless of
        which transport delivered it.
        """
        now = time.monotonic() if now is None else now

        print_stats = payload.get("print_stats")
        if isinstance(print_stats, dict):
            state = print_stats.get("state")
            if isinstance(state, str):
                self.set_printer_mode(normalize_printer_mode(state), now=now)

            if "print_duration" in print_stats:
                self.elapsed = print_stats.get("print_duration")

            info = print_stats.get("info")
            current_layer = info.get("current_layer") if isinstance(info, dict) else None
            # `current_layer` is only populated by a `SET_PRINT_STATS_INFO`
            # gcode macro (or estimated by a UI), so it may legitimately be
            # absent/None throughout a print -- only react when it actually
            # changes, and don't flash for the very first value observed
            # (that's "we just started tracking layers", not "a layer
            # change just happened").
            if isinstance(current_layer, int) and current_layer != self.last_layer:
                if self.last_layer is None:
                    self.last_layer = current_layer
                else:
                    self.update_from_layer_change({"layer": current_layer}, now=now)

        display_status = payload.get("display_status")
        if isinstance(display_status, dict) and "progress" in display_status:
            self.set_progress(display_status.get("progress"), elapsed=self.elapsed, remaining=self.remaining)

        motion_report = payload.get("motion_report")
        if isinstance(motion_report, dict) and "live_velocity" in motion_report:
            velocity = motion_report.get("live_velocity") or 0.0
            self.update_from_motion({"active": velocity > 0.5, "velocity": velocity})

        # Any other subscribed object exposing `temperature` (heater_bed,
        # extruder, extruder1, ...) is treated as a heater reading -- this
        # covers whichever heaters the connector is actually configured to
        # subscribe to without hardcoding their names here.
        heaters = {
            name: value
            for name, value in payload.items()
            if name not in {"print_stats", "display_status", "motion_report"} and isinstance(value, dict) and "temperature" in value
        }
        if heaters:
            self.update_from_temperature(heaters, now=now)

    def update_from_temperature(self, payload: dict[str, Any], *, now: float | None = None) -> None:
        for name, value in payload.items():
            if isinstance(value, dict):
                self.set_temperature(
                    name,
                    actual=value.get("actual") or value.get("temp") or value.get("temperature"),
                    target=value.get("target"),
                    now=now,
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
