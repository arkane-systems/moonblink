# Moonblink implementation instructions

## Goal
Build Moonblink as a small Python 3.10+ service that reads Moonraker/Klipper state and renders printer status on a Pimoroni Blinkt! strip.

## Non-negotiables from the SPEC
- Use Moonraker WebSocket events for real-time updates.
- Use REST polling for initial state and periodic sanity checks.
- Keep the renderer pure: state in, 8-pixel frame out.
- Inject Blinkt hardware access so tests can run without physical LEDs.
- Limit LED updates to 20 Hz or less and smooth transitions.
- Support a local-only control API on 127.0.0.1.
- Provide systemd, Makefile install/uninstall support, config defaults, and tests.

## Implementation order
1. Define the package layout and shared types.
2. Implement the state model and event normalization.
3. Implement the pure renderer and priority rules.
4. Implement the animator and Blinkt hardware adapter.
5. Implement the Moonraker connector with reconnect/backoff and REST fallback.
6. Implement the local HTTP API.
7. Add config loading, service entrypoint, systemd unit, and Makefile targets.
8. Add unit, integration, and CI coverage.

## Design constraints
- Prefer `asyncio` for connector, API, and background orchestration.
- Treat critical errors, alerts, warnings, active print, and idle as ordered priorities.
- Keep the LED mapping configurable, but preserve the SPEC defaults.
- Avoid sustained bright white or red output; flashes and strobes must be duty-limited.
- Clear the Blinkt on shutdown.

## Testing guidance
- Unit-test renderer behavior with synthetic states.
- Use fake Blinkt and fake Moonraker clients for integration tests.
- Verify pause/resume, layer flashes, filament alerts, and critical errors explicitly.
- Keep config validation strict and fail fast on invalid files.

## Install guidance
- Follow the crowsnest-style install model: clone into the Klipper/Moonraker home directory, then use `make install` and `make uninstall` to manage files and service links.
- If Update Manager support is added, keep it optional and explicit.
