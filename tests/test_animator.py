from __future__ import annotations

import asyncio
import logging
import unittest

from moonblink.animator import AnimationConfig, FrameAnimator, NullBlinktDriver
from moonblink.renderer import RenderedFrame


class FrameAnimatorModeLoggingTests(unittest.TestCase):
    """FrameAnimator narrates rendering *mode* transitions at INFO, not every frame."""

    def test_logs_once_per_mode_transition_not_per_frame(self) -> None:
        logger = logging.getLogger("moonblink.test.animator-mode")
        animator = FrameAnimator(NullBlinktDriver(), AnimationConfig(max_hz=1000, transition_ms=0), log=logger)

        idle_frame = RenderedFrame(pixels=((0, 0, 255),) * 8, brightness=0.3, mode="idle")
        # A continuously-varying "idle breathing" frame -- same mode, only
        # brightness/color drifts -- must not trigger repeated INFO logs.
        idle_frame_drifted = RenderedFrame(pixels=((0, 0, 200),) * 8, brightness=0.28, mode="idle")
        printing_frame = RenderedFrame(pixels=((0, 255, 0),) * 8, brightness=0.3, mode="printing")

        with self.assertLogs(logger, level="INFO") as captured:
            asyncio.run(animator.present(idle_frame, now=0.0))
            asyncio.run(animator.present(idle_frame_drifted, now=0.01))
            asyncio.run(animator.present(idle_frame_drifted, now=0.02))
            asyncio.run(animator.present(printing_frame, now=0.03))

        messages = [record.getMessage() for record in captured.records]
        self.assertEqual(len(messages), 2)
        self.assertIn("idle", messages[0])
        self.assertIn("printing", messages[1])


if __name__ == "__main__":
    unittest.main()
