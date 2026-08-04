# moonblink
Moonraker data exposed via Blinkt!

## Requirements

* Python 3.10+
* `aiohttp` and `pyyaml` (installed automatically as regular dependencies)
* On the Raspberry Pi running the service: the `blinkt` package and a real
  Blinkt! strip. Install it with the `hardware` extra:

  ```bash
  pip install -e '.[hardware]'
  ```

  `blinkt` depends on `RPi.GPIO`, which only builds on Raspberry Pi
  hardware, so it's kept as an optional extra rather than a hard
  dependency -- this lets the rest of the package install and its test
  suite run on any development machine or CI runner. In normal
  (non-`--simulate`) operation, `moonblink` requires real hardware and
  will exit immediately with a clear error if `blinkt` isn't
  installed/available; use `--simulate` to run without it.

## Install

Clone the repository into your Moonraker/Klipper home directory, then run:

```bash
make install
sudo systemctl enable --now moonblink
```

`make uninstall` removes the service unit, installed config, and shared
files.

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
  automatically raise/clear heater alerts from temperature readings.
* `night_mode` — `enabled`, `dim_to`, and a `start`/`end` (`HH:MM`,
  midnight-wrapping) window during which brightness is automatically
  capped.

## Run

```bash
python3 -m moonblink.main --config config/moonblink.yaml
```

### Manual testing without Moonraker or hardware

```bash
python3 -m moonblink.main --simulate
```

`--simulate` cycles through a built-in demo sequence (idle → printing →
layer-change flash → paused → filament runout alert → acknowledge → resume
→ critical thermal-runaway error → idle) using a no-op LED driver, so the
full rendering/priority/animation pipeline can be exercised on any machine.
