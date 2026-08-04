from __future__ import annotations

import asyncio
import unittest

from moonblink.animator import AnimationConfig, FrameAnimator, NullBlinktDriver
from moonblink.renderer import RenderConfig
from moonblink.simulate import build_demo_steps, run_simulation
from moonblink.state import PrinterState


class SimulateModeTests(unittest.TestCase):
    def test_demo_sequence_covers_key_scenarios(self) -> None:
        names = [step.name for step in build_demo_steps()]
        self.assertIn("printing:start", names)
        self.assertIn("printing:layer-change", names)
        self.assertIn("paused", names)
        self.assertIn("filament-runout", names)
        self.assertIn("critical:thermal-runaway", names)

    def test_run_simulation_once_applies_every_step_and_presents_frames(self) -> None:
        state = PrinterState()
        animator = FrameAnimator(NullBlinktDriver(), AnimationConfig(max_hz=1000, transition_ms=0))
        seen: list[str] = []

        # Speed the demo up drastically so the test runs quickly, and only
        # go through it once.
        fast_steps = [type(step)(step.name, step.action, hold_s=0.01) for step in build_demo_steps()]

        asyncio.run(
            run_simulation(
                state,
                animator,
                RenderConfig(),
                steps=fast_steps,
                repeat=False,
                on_step=lambda step: seen.append(step.name),
            )
        )

        self.assertEqual(seen, [step.name for step in fast_steps])
        # Final step resets to idle.
        self.assertEqual(state.printer_mode, "idle")
        self.assertEqual(state.alerts, {})


if __name__ == "__main__":
    unittest.main()
