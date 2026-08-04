"""Synthetic demo mode for manual testing without Moonraker or hardware.

``--simulate`` drives the same :class:`~moonblink.state.PrinterState` /
:class:`~moonblink.renderer.render_frame` / animator pipeline as a live
Moonraker connection, but feeds it a small built-in sequence of state
transitions instead of real events, so the visual behaviour (progress fill,
layer flash, pause, filament alert escalation, critical error) can be
exercised anywhere -- no Moonraker instance, network, or Blinkt! hardware
required.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from .animator import FrameAnimator
from .renderer import RenderConfig, render_frame
from .state import ALERT_CRITICAL, ALERT_WARNING, PRINTER_IDLE, PRINTER_PAUSED, PRINTER_PRINTING, PrinterState

StepAction = Callable[[PrinterState], None]


@dataclass(slots=True)
class SimulationStep:
    """A single named transition applied to the state, held for ``hold_s`` seconds."""

    name: str
    action: StepAction
    hold_s: float = 2.0


def build_demo_steps() -> list[SimulationStep]:
    """Return the canned idle -> print -> alert -> critical -> idle demo sequence."""

    def start_idle(state: PrinterState) -> None:
        state.set_printer_mode(PRINTER_IDLE)
        state.clear_all_alerts()
        state.set_progress(0.0)

    def start_printing(state: PrinterState) -> None:
        state.set_printer_mode(PRINTER_PRINTING)
        state.set_progress(0.1)
        state.set_motion(True, velocity=80.0)

    def advance_progress(state: PrinterState) -> None:
        state.set_progress(0.55)

    def layer_change(state: PrinterState) -> None:
        state.set_layer_change(42, flash_duration=0.3)

    def pause_print(state: PrinterState) -> None:
        state.set_printer_mode(PRINTER_PAUSED)
        state.set_motion(False)
        state.set_user_effect("pause", duration=0.6)

    def filament_runout(state: PrinterState) -> None:
        state.add_alert("filament-runout", kind="filament", severity=ALERT_WARNING, message="Filament runout detected")

    def acknowledge_runout(state: PrinterState) -> None:
        state.acknowledge_alert("filament-runout")
        state.set_user_effect("ack", duration=0.6)

    def resume_print(state: PrinterState) -> None:
        state.set_printer_mode(PRINTER_PRINTING)
        state.set_motion(True, velocity=80.0)
        state.set_user_effect("resume", duration=0.6)

    def thermal_runaway(state: PrinterState) -> None:
        state.add_alert("thermal-runaway", kind="heater", severity=ALERT_CRITICAL, message="Thermal runaway detected")

    def clear_and_idle(state: PrinterState) -> None:
        state.clear_all_alerts()
        state.set_printer_mode(PRINTER_IDLE)
        state.set_progress(0.0)
        state.set_motion(False)

    return [
        SimulationStep("idle", start_idle, hold_s=2.0),
        SimulationStep("printing:start", start_printing, hold_s=2.0),
        SimulationStep("printing:progress", advance_progress, hold_s=2.0),
        SimulationStep("printing:layer-change", layer_change, hold_s=1.0),
        SimulationStep("paused", pause_print, hold_s=2.0),
        SimulationStep("filament-runout", filament_runout, hold_s=2.0),
        SimulationStep("filament-runout:ack", acknowledge_runout, hold_s=1.5),
        SimulationStep("printing:resume", resume_print, hold_s=2.0),
        SimulationStep("critical:thermal-runaway", thermal_runaway, hold_s=3.0),
        SimulationStep("idle:reset", clear_and_idle, hold_s=2.0),
    ]


async def run_simulation(
    state: PrinterState,
    animator: FrameAnimator,
    render_config: RenderConfig,
    *,
    steps: Sequence[SimulationStep] | None = None,
    repeat: bool = True,
    on_step: Callable[[SimulationStep], Awaitable[None] | None] | None = None,
) -> None:
    """Run the demo sequence, presenting a frame after every step and while holding.

    When ``repeat`` is False the sequence runs exactly once through, which is
    primarily useful for tests; the default (``True``) loops forever, which
    is what ``--simulate`` uses for interactive manual testing.
    """
    demo_steps = list(steps) if steps is not None else build_demo_steps()

    while True:
        for step in demo_steps:
            step.action(state)
            if on_step is not None:
                result = on_step(step)
                if asyncio.iscoroutine(result):
                    await result

            deadline = time.monotonic() + step.hold_s
            while True:
                await animator.present(render_frame(state, render_config))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(remaining, 1.0 / max(animator.max_hz, 1.0)))
        if not repeat:
            return
