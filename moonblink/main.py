"""Moonblink service entrypoint."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from .api import ControlCallbacks, ControlServer
from .animator import AnimationConfig, FrameAnimator, NullBlinktDriver
from .connector import MoonrakerConfig, MoonrakerConnector
from .renderer import RenderConfig, render_frame
from .state import PrinterState


@dataclass(slots=True)
class MoonblinkRuntime:
    state: PrinterState
    renderer_config: RenderConfig
    animation_config: AnimationConfig
    moonraker_config: MoonrakerConfig
    api_bind_address: str = "127.0.0.1"
    api_port: int = 8765

    async def run(self) -> None:
        driver = NullBlinktDriver()
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
        connector = MoonrakerConnector(
            self.moonraker_config,
            self.state,
            on_state_change=lambda state: animator.present(render_frame(state, self.renderer_config)),
        )
        try:
            await connector.start()
        finally:
            api.stop()
            animator.clear()

    def _apply_test_pattern(self, pattern: str) -> dict[str, str]:
        self.state.set_user_effect(pattern or "test")
        return {"pattern": pattern}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moonblink")
    parser.add_argument("--config", default="config/moonblink.yaml")
    parser.add_argument("--simulate", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    parser.parse_args()
    runtime = MoonblinkRuntime(
        state=PrinterState(),
        renderer_config=RenderConfig(),
        animation_config=AnimationConfig(),
        moonraker_config=MoonrakerConfig(),
    )
    asyncio.run(runtime.run())


if __name__ == "__main__":
    main()
