# moonblink
Moonraker data exposed via Blinkt!

## Requirements

* Python 3.10+
* `aiohttp` and `pyyaml` (listed in `requirements.txt`, installed automatically
  by `make install` into a dedicated virtualenv -- see below)
* On the Raspberry Pi running the service: the `blinkt` package and a real
  Blinkt! strip (listed in `requirements-hardware.txt`, also installed
  automatically by `make install` unless `WITH_HARDWARE=0` is set).

  `blinkt` depends on `RPi.GPIO`, which only builds on Raspberry Pi
  hardware, so it's kept separate from the base dependencies -- this lets
  the rest of the package install and its test suite run on any
  development machine or CI runner. In normal (non-`--simulate`)
  operation, `moonblink` requires real hardware and will exit immediately
  with a clear error if `blinkt` isn't installed/available; use
  `--simulate` to run without it.

  For local development/testing (not a full `make install`), install the
  package directly with its extras instead:

  ```bash
  pip install -e '.[hardware]'
  ```

## Install

Clone the repository into your Moonraker/Klipper home directory (e.g.
`/home/pi/moonblink`), then run:

```bash
make install
sudo systemctl enable --now moonblink
```

`make install` creates a dedicated virtualenv at `.venv` inside the cloned
repository (mirroring how Moonraker/Klipper manage their own Python
environments) and installs `requirements.txt`/`requirements-hardware.txt`
into it -- this avoids fighting with the system Python, which recent
Raspberry Pi OS releases block from `pip install` outside a venv (PEP
668). Only third-party dependencies are installed into `.venv`; moonblink
itself always runs directly from the git checkout (`WorkingDirectory` in
`moonblink.service`), so pulling updates (e.g. via Moonraker's Update
Manager) takes effect on the next service restart with no reinstall step
needed. The installed systemd unit's `ExecStart` invokes
`.venv/bin/python3` rather than the system `python3`.

To skip installing the `blinkt` hardware extra (e.g. testing the install
flow on a non-Pi machine), use:

```bash
make install WITH_HARDWARE=0
```

Per Klipper convention, nothing is installed into system directories other
than the systemd unit itself (in `SYSTEMD_DIR`); the venv lives inside the
repo clone and the config file is copied into your Moonraker `CONFIG_DIR`.

`make uninstall` removes the installed service unit, config, and the
`.venv` directory.

### Moonraker Update Manager (optional)

Update Manager registration is off by default. Opt in explicitly with:

```bash
make install ENABLE_UPDATE_MANAGER=1
```

or register/unregister it independently of install/uninstall:

```bash
make update-manager-install
make update-manager-uninstall
```

This writes a `[update_manager moonblink]` section to
`~/printer_data/config/moonraker.conf.d/moonblink.conf` (make sure your
`moonraker.conf` has an `[include moonraker.conf.d/*.conf]` directive) of
`type: git_repo`, pointing at this checkout's `path`/`origin`. It also
sets `virtualenv` to the `.venv` created by `make install` and
`requirements` to the tracked requirements file (`requirements-pi.txt`
with the hardware extra, or plain `requirements.txt` when installed with
`WITH_HARDWARE=0`), so Moonraker automatically reinstalls Python
dependencies into `.venv` whenever that file changes on update. It also
sets `managed_services: moonblink` so the systemd service is restarted
automatically after each update -- no manual `pip install`/`systemctl
restart` steps are required.

## Configuration

`config/moonblink.yaml` is loaded and strictly validated at startup --
unknown keys, out-of-range values (e.g. an invalid `brightness_max`), or
malformed color/time entries fail fast with a descriptive error rather than
falling back to defaults silently. See the comments in that file for all
available options, including:

* `moonraker` — WebSocket/REST URLs.
* `api` — local control API bind address/port.
* `brightness_max`, `update_rate_hz`, `flash_duration_ms` — rendering/animation limits.
* `critical_alert_escalate_after_s` — how long a critical *alert* (e.g.
  filament runout) can go unacknowledged before it escalates from a
  pixel-7 blink to a full-strip strobe. `printer_mode == error` (thermal
  runaway, e-stop, etc.) always strobes immediately regardless of this
  setting.
* `colors` — per-state/indicator colors.
* `temp_thresholds` — `warning_c` / `critical_c` off-target deltas that
  automatically raise/clear heater alerts from temperature readings, plus
  warmup/cooldown gating controls: `progress_min_change_c` (minimum
  movement toward target that counts as progress) and `progress_stall_s`
  (how long progress can stall after a target change before
  warning/critical alerts are allowed again).
* `night_mode` — `enabled`, `dim_to`, and a `start`/`end` (`HH:MM`,
  midnight-wrapping) window during which brightness is automatically
  capped.

## Run

If installed via `make install`, the systemd service already runs the
correct interpreter (`.venv/bin/python3`) automatically. To run manually
using the same environment:

```bash
.venv/bin/python3 -m moonblink.main --config config/moonblink.yaml
```

### Manual testing with or without hardware

```bash
.venv/bin/python3 -m moonblink.main --simulate
```

(Or, in a development checkout without a `make install`-created `.venv`,
use whatever interpreter/virtualenv you've installed the package's
dependencies into, e.g. plain `python3` after `pip install -e .`.)

`--simulate` cycles through a built-in demo sequence (idle → printing →
layer-change flash → paused → filament runout alert → acknowledge → resume
→ critical thermal-runaway error → idle). It automatically drives the real
Blinkt! strip if one is detected (letting you exercise the full
rendering/animation/hardware pipeline end-to-end on the printer itself),
and falls back to a no-op driver if it isn't (e.g. on a dev machine) --
either way, every rendering *mode* transition is logged to the console so
the sequence stays visible without a strip attached, or over SSH. Run with
`--log-level debug` to additionally see every raw pixel value written to
the driver (useful for confirming the console echo matches actual hardware
output).

### Logging

Moonblink logs to stdout with a systemd/journald-friendly format (no
timestamp -- journald adds its own). Control verbosity with `--log-level`
(`debug`, `info` [default], `warning`, `error`, or `critical`):

```bash
.venv/bin/python3 -m moonblink.main --config config/moonblink.yaml --log-level debug
```

When running as the installed systemd service, view logs with:

```bash
journalctl -u moonblink -f
```

(the unit sets `SyslogIdentifier=moonblink`, so `journalctl -t moonblink -f`
also works). At the default `info` level you'll see connection state to
Moonraker (websocket connect/disconnect, REST snapshot failures, reconnect
backoff), local control API requests (`/ack`, `/brightness`,
`/test-pattern`), and rendering mode transitions -- useful for confirming
the service is actually talking to Moonraker if the strip appears idle
unexpectedly. Use `--log-level debug` for finer detail, including every
unhandled Moonraker message type and raw pixel writes sent to the Blinkt!.
