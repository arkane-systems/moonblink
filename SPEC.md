# Blinkt! lighting service

## Overview

A compact Python service that connects to Moonraker/Klipper on a Raspberry Pi and drives a Pimoroni Blinkt! (8 RGB LEDs) to present an informative, glanceable, and attractive status display inside a transparent electronics case. The service uses Moonraker WebSocket events for low-latency signals (layer change, motion, errors) and REST endpoints for periodic state checks (print progress, temperatures). It exposes a small local HTTP control API for acknowledgements, brightness, and test patterns.

## Data sources (Moonraker / Klipper)

Primary (real-time) — WebSocket events

 * `notify_status_update` — printer state changes (printing, paused, idle, error).
 * `notify_gcode_response` / `gcode_response` — last gcode responses and errors.
 * `notify_print_progress` / `print_stats` events — progress updates, elapsed/remaining.
 * `notify_temperature_update` — heater actual/target updates (hotend(s), bed).
 * `notify_motion_update` or `toolhead` position events — motion/velocity (if available).
 * `notify_layer_change` or `print_stats` layer info — layer change events (timelapse sync).

## Secondary (periodic) — REST endpoints

* `GET /printer/objects/query` — query print_stats, heater, toolhead, power, display_status.
* `GET /printer/objects/list` — for available objects and fields.
* `GET /printer/objects/print_job` — file name, progress, times.
* System endpoints for Pi CPU/temperature (optional) if available.

**Why both:** WebSocket for instant events (layer change, errors, motion), REST for occasional sanity checks and initial state.

## LED mapping (pixel indices 0–7)

All pixel indices are left→right: **0..7**.

| Pixel(s) | Primary use              | Color / Behavior |
|----------|--------------------------|------------------|
| 0	       | Global printer state     |	Solid color: **green**=printing; **blue**=idle; **yellow**=paused; **red**=error |
| 1–6      | Print progress bar	      | Fill left→right proportionally; gradient **cyan→magenta** as it fills |
| 7        | Alarm / heater indicator | Blink **red** for critical; pulse **amber** for off-target heaters; brightness indicates delta |
| All      | Layer change / timelapse flash | Short white flash across all pixels (200–400 ms) on layer snapshot |

**Overlay rules:** motion spark and alerts overlay progress pixels without permanently replacing them (see Priority rules).

## Animations and priority rules

### Priority order (highest → lowest)

1. **Critical error** (thermal runaway, heater fault, PSU fail, emergency stop) — full-LED red strobe until cleared.
2. **Critical alerts** (filament runout, high-temp off-target) — pixel 7 blinking red; may escalate to full strobe if unacknowledged.
3. **Warnings** (heater off-target, fan failure) — pixel 7 pulses amber; progress paused overlay.
4. **Active print** — progress bar (1–6) + motion spark overlay; pixel 0 solid green.
5. **Idle** — pixel 0 steady blue; subtle breathing or slow color cycle across 1–6.
6. **User** interactions (pause/resume/acknowledge) — short distinct pulses: yellow pulse for pause, green pulse for resume, dim pulse for acknowledge.

### Animation primitives

* **Solid:** constant color.
* **Pulse:** smooth fade in/out (period configurable).
* **Blink:** on/off at fixed duty cycle.
* **Wipe:** sequential lighting left→right.
* **Spark:** single bright pixel moving across progress pixels while motion detected.
* **Flash:** short full-white flash for timelapse/layer change.

### Rate-limiting & smoothing

* Limit LED frame updates to **≤ 20 Hz**; prefer **10–15 Hz** for smooth fades.
* Interpolate color transitions over **100–300 ms** to avoid flicker.
* Cap global brightness (configurable) to avoid heating and glare.

## Architecture & implementation notes

### Tech stack

* **Language:** Python 3.10+
* **Blinkt control:** `blinkt` Python library (Pimoroni).
* **WebSocket client:** `websockets` or `aiohttp` (async).
* **REST:** `requests` or `aiohttp` for periodic queries.
* **Service runner:** systemd service.
* **Optional:** small local Flask/FastAPI endpoint for control.

### High-level components

1. **Moonraker connector** — WebSocket subscription + REST fallback.
2. **State model** — canonical state: `{printer_state, progress, temps, motion, last_layer, alerts}`.
3. **Renderer** — maps state → LED frame (8 RGB tuples).
4. **Animator** — interpolates between frames, enforces rate limits.
5. **Controller API** — local HTTP endpoints: `/ack`, `/brightness`, `/test-pattern`.
6. **Config loader** — YAML/JSON config for colors, thresholds, brightness, night mode schedule.
7. **Logger & diagnostics** — log events and LED frames for debugging.

### Data flow (simplified)

1. Connect WebSocket; on connect, fetch initial state via REST.
2. Update state model on events.
3. Renderer computes target frame and animation instructions.
4. Animator interpolates and writes frames to Blinkt! via `blinkt.set_pixel()` and `blinkt.show()`.
5. Control API can override or acknowledge alerts.

### Example event-to-frame pseudocode

```python
# Pseudocode (not runnable)
on_event(event):
    update_state(event)
    frame = render_frame(state)
    animator.transition_to(frame, duration=0.2)
    blinkt.show()
```

### WebSocket vs Polling

* **Use WebSocket** for: layer change, motion, immediate errors, print start/stop/pause/resume.
* **Poll REST** every **5–10 s** for progress and temperature sanity checks.
* Reconnect/backoff strategy for WebSocket.

### Blinkt usage notes

* Use `blinkt.set_pixel(index, r, g, b, brightness)` then `blinkt.show()`.
* Call `blinkt.clear()` on shutdown.
* Respect global brightness; default **0.2–0.4** recommended inside transparent case.

### Configuration and safety

#### Config options

* `colors`: mapping for state colors (printing, idle, paused, error).
* `brightness_max`: 0.0–1.0.
* `night_mode`: schedule to dim after a time.
* `temp_thresholds`: heater off-target thresholds (e.g., 5°C warning, 15°C critical).
* `flash_duration_ms`: layer flash length.
* `update_rate_hz`: max LED update frequency.

**Note:** Keep configuration file in Klipper/Moonraker/Mainsail shared configuration directory.

#### Safety & UX

* Avoid sustained full-white or full-bright animations; prefer short flashes.
* If Pi CPU temp > threshold, reduce animation complexity and brightness.
* Provide a config option to disable layer flashes for night use.
* Ensure critical alerts are unmissable but not damaging (use duty-limited strobes).

## Testing, validation, and acceptance criteria

### Unit tests

* Renderer: given synthetic states, produce expected frames.
* Priority rules: higher-priority states override lower-priority visuals.
* Config parsing: invalid configs produce clear errors.

### Integration tests

* Simulate Moonraker WebSocket events (start, layer change, pause, filament out, error) and verify LED frames and transitions.
* Test REST fallback when WebSocket disconnects.
* Test control API endpoints: `/ack`, `/brightness`, `/test-pattern`.

### Manual validation

* Run on Pi with Blinkt! attached; verify:
  * Start print → green pixel 0 + progress fill on 1–6.
  * Layer change → short white flash.
  * Pause → pixel 0 yellow pulse; progress frozen.
  * Filament runout → alternating orange on progress + pixel 7 blinking red.
  * Critical error → full red strobe until acknowledged.

### Acceptance criteria

* Service runs as systemd unit and auto-starts on boot.
* All mappings in LED mapping table implemented and configurable.
* WebSocket reconnection and REST fallback implemented.
* Local control API implemented and documented.
* Tests (unit + integration) pass in CI.

### Minimal local control API (HTTP)

All endpoints are local-only (bind to 127.0.0.1 by default).

| Method | Path | Body | Behavior |
|--------|------|------|----------|
| POST | `/ack` | `{ "alert_id": "string" }` | Acknowledge alert; stop blinking for that alert. |
| POST | `/brightness` | `{ "level": 0.0 }` | Set global brightness (0.0–1.0); persists to config. |
| POST | `/test-pattern` | `{ "pattern": "rainbow" }` | Force a test pattern for N seconds; returns current state after. |

## Installation

Installation (and therefore repo layout) should follow the model of crowsnest ( https://github.com/mainsail-crew/crowsnest ) in which the repo is cloned into the Klipper/Moonraker home directory and `make install` and `make uninstall` update configuration files, systemd unit links, and so forth - as described here: https://docs.mainsail.xyz/crowsnest/setup/installation/

The installation procedure should also, if requested, configure Moonraker Update Manager to allow updating of the Moonblink installation.

## Deliverables (what to implement)

* `SPEC.md` (this document) in repo root.
* `README.md` with install and run instructions.
* `config/moonblink.yaml` with color and threshold defaults.
* `Makefile` to install and configure/uninstall Moonblink
* `moonblink/`:
  * `connector.py` (WebSocket + REST client).
  * `state.py` (state model).
  * `renderer.py` (state → frame).
  * `animator.py` (interpolation + rate limiting).
  * `api.py` (local control endpoints).
  * `main.py` (service entrypoint, systemd-friendly).
  * `moonblink.service` (systemd unit file)
* `tests/`:
  * Unit tests for renderer and priority rules.
  * Integration tests simulating events.
* CI pipeline: run unit tests and linting.

---

## Implementation hints for GitHub Copilot

* Use `asyncio` for WebSocket and REST concurrency.
* Keep renderer pure (input state → output frame) to make unit testing trivial.
* Use dependency injection for Blinkt hardware access so tests can run without hardware.
* Provide a `--simulate` mode to replay recorded Moonraker events for manual testing.
