"""Moonblink service entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass

from .animator import AnimationConfig, ConsoleEchoDriver, FrameAnimator, NullBlinktDriver
from .api import ControlCallbacks, ControlServer
from .config import ConfigError, MoonblinkConfig, effective_render_config, load_config
from .connector import MoonrakerConfig, MoonrakerConnector
from .logging_setup import configure_logging
from .renderer import RenderConfig, render_frame
from .simulate import run_simulation
from .state import PrinterState

logger = logging.getLogger("moonblink.main")  # not __name__: this module also runs as
# __main__ via `python -m moonblink.main`, which would otherwise put logs under
# the "__main__" logger instead of the "moonblink" hierarchy configure_logging()
# sets up, silently suppressing them at the default level.


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
        logger.info(
            "starting moonblink (mode=%s, api=%s:%d)",
            "simulate" if self.simulate else "live",
            self.api_bind_address,
            self.api_port,
        )
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
                await run_simulation(
                    self.state,
                    animator,
                    self._current_render_config(),
                    on_step=lambda step: logger.info("simulate: step '%s' (hold %.1fs)", step.name, step.hold_s),
                )
            else:
                await self._run_live(animator)
        finally:
            api.stop()
            animator.clear()
            logger.info("moonblink stopped")

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
        from .hardware import BlinktHardwareDriver, BlinktHardwareError

        if self.simulate:
            # --simulate uses real Blinkt! hardware when it's available (so
            # the full rendering/animation/hardware stack can be exercised
            # end-to-end), falling back to a no-op driver otherwise. Either
            # way frames are echoed to the console/log so behaviour is
            # visible over SSH/journalctl with or without a physical strip.
            try:
                hardware_driver = BlinktHardwareDriver()
            except BlinktHardwareError as exc:
                logger.info("simulate: no Blinkt! hardware available (%s); echoing frames to the console only", exc)
                return ConsoleEchoDriver(NullBlinktDriver())
            logger.info("simulate: Blinkt! hardware detected; driving real LEDs and echoing frames to the console")
            return ConsoleEchoDriver(hardware_driver)

        # Production runs assume real Blinkt! hardware is present and must
        # fail fast (not silently fall back to a no-op driver) if it isn't.
        try:
            return BlinktHardwareDriver()
        except BlinktHardwareError as exc:
            logger.error("%s", exc)
            logger.error("run with --simulate to test without hardware")
            raise SystemExit(1) from exc

    def _apply_test_pattern(self, pattern: str) -> dict[str, str]:
        self.state.set_user_effect(pattern or "test")
        return {"pattern": pattern}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moonblink")
    parser.add_argument("--config", default="config/moonblink.yaml")
    parser.add_argument("--simulate", action="store_true", help="run a built-in synthetic demo sequence; uses real Blinkt! hardware if available, console-only otherwise")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="logging verbosity written to stdout (captured by journald under systemd). Default: info",
    )
    return parser


def build_runtime(args: argparse.Namespace) -> MoonblinkRuntime:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        logger.error("invalid config '%s': %s", args.config, exc)
        raise SystemExit(1) from exc

    logger.info("loaded config from '%s'", args.config)
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
    configure_logging(args.log_level)
    runtime = build_runtime(args)
    asyncio.run(runtime.run())


if __name__ == "__main__":
    main()
