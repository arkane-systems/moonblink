# moonblink
Moonraker data exposed via Blinkt!

## Install

Clone the repository into your Moonraker/Klipper home directory, then run:

```bash
make install
sudo systemctl enable --now moonblink
```

`make uninstall` removes the service unit, installed config, and shared files.

## Run

```bash
python3 -m moonblink.main --config config/moonblink.yaml
```
