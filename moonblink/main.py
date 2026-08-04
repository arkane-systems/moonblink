"""Moonblink service entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from .animator import AnimationConfig, FrameAnimator, NullBlinktDriver
from .api import ControlCallbacks, ControlServer
from .config import ConfigError, MoonblinkConfig, effective_render_config, load_config
from .connector import MoonrakerConfig, MoonrakerConnector
from .renderer import RenderConfig, render_frame
from .simulate import run_simulation
from .state import PrinterState


@dataclass(slots=True)
class MoonblinkRuntime:
    state: PrinterState
    renderer_config: RenderConfig
    animation_config: AnimationConfig
    moonraker_config: MoonrakerConfig
    config: MoonblinkConfig
    api_bind_address: str = "127.0.0.1"
    api_port: int = 8765
    simulate: bool = False

    async def run(self) -> None:
        driver = self._build_driver()
        animator = FrameAnimator(driver, self.animation_config)
        api = ControlServer(
            bind_address=self.api_bind_address,
            port=self.api_port,
            callbacks=ControlCallbacks(
                ack=self.state.acknowledge_alert,
                set_brightness=lambda level: setattr(self.renderer_config, "brightness_max", max(0.0, min(1.0, float(level)))),
                test_pattern=self._apply_test_pattern,
                current_state=lambda: {
                    "mode": self.state.printer_mode,
                    "progress": self.state.progress,
                    "alerts": list(self.state.alerts),
                },
            ),
        )
        api.start()
        try:
            if self.simulate:
                await run_simulation(self.state, animator, self._current_render_config())
            else:
                await self._run_live(animator)
        finally:
            api.stop()
            animator.clear()

    async def _run_live(self, animator: FrameAnimator) -> None:
        def on_state_change(state: PrinterState):
            state.evaluate_temperature_alerts(
                warning_c=self.config.temp_thresholds.warning_c,
                critical_c=self.config.temp_thresholds.critical_c,
            )
            return animator.present(render_frame(state, self._current_render_config()))

        connector = MoonrakerConnector(
            self.moonraker_config,
            self.state,
            on_state_change=on_state_change,
        )
        await connector.start()

    def _current_render_config(self) -> RenderConfig:
        return effective_render_config(self.renderer_config, self.config.night_mode)

    def _build_driver(self):
        if self.simulate:
            return NullBlinktDriver()

        # Production runs assume real Blinkt! hardware is present and must
        # fail fast (not silently fall back to a no-op driver) if it isn't.
        from .hardware import BlinktHardwareDriver, BlinktHardwareError

        try:
            return BlinktHardwareDriver()
        except BlinktHardwareError as exc:
            print(f"moonblink: {exc}", file=sys.stderr)
            print("moonblink: run with --simulate to test without hardware", file=sys.stderr)
            raise SystemExit(1) from exc

    def _apply_test_pattern(self, pattern: str) -> dict[str, str]:
        self.state.set_user_effect(pattern or "test")
        return {"pattern": pattern}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moonblink")
    parser.add_argument("--config", default="config/moonblink.yaml")
    parser.add_argument("--simulate", action="store_true", help="run a built-in synthetic demo sequence, no Moonraker/hardware required")
    return parser


def build_runtime(args: argparse.Namespace) -> MoonblinkRuntime:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"moonblink: invalid config '{args.config}': {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    return MoonblinkRuntime(
        state=PrinterState(),
        renderer_config=config.render,
        animation_config=config.animation,
        moonraker_config=config.moonraker,
        config=config,
        api_bind_address=config.api_bind_address,
        api_port=config.api_port,
        simulate=args.simulate,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    runtime = build_runtime(args)
    asyncio.run(runtime.run())


if __name__ == "__main__":
    main()
