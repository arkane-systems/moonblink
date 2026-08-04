SYSTEMD_DIR ?= /etc/systemd/system
CONFIG_DIR ?= /home/pi/printer_data/config
UPDATE_MANAGER_DIR ?= /home/pi/printer_data/config/moonraker.conf.d
SERVICE_NAME ?= moonblink
# Absolute path of the cloned repository, as Moonraker's Update Manager
# needs an absolute `path`/`virtualenv`. Defaults to wherever `make` is
# actually being run from (the clone itself), per the crowsnest-style
# fixed-clone-location convention -- override if cloned somewhere unusual.
REPO_PATH ?= $(CURDIR)
ORIGIN ?= https://github.com/arkane-systems/moonblink
PRIMARY_BRANCH ?= master
PYTHON ?= python3
# Dedicated virtualenv for moonblink's third-party Python dependencies
# (pyyaml, aiohttp, blinkt), kept inside the cloned repo directory. This
# mirrors how Moonraker/Klipper manage their own Python environments, and
# avoids fighting with the system Python, which on current Raspberry Pi OS
# refuses `pip install` outside a venv (PEP 668). Only dependencies are
# installed into it -- moonblink itself always runs directly from this git
# checkout (WorkingDirectory in moonblink.service), so `git pull` via
# Moonraker's Update Manager takes effect immediately without needing a
# reinstall, same as other Klipper-ecosystem services.
VENV_DIR ?= .venv
# Whether to install the `blinkt` hardware extra (requires RPi.GPIO, which
# only builds on real Raspberry Pi hardware). Defaults on since `make
# install` targets an actual Pi + Blinkt! deployment; set WITH_HARDWARE=0
# to skip it (e.g. for --simulate-only use on a non-Pi machine).
WITH_HARDWARE ?= 1
# Update Manager registration is optional per AGENTS.md -- it is never run
# implicitly by `install`. Pass ENABLE_UPDATE_MANAGER=1 to `make install`,
# or run `make update-manager-install` explicitly, to opt in.
ENABLE_UPDATE_MANAGER ?= 0

.PHONY: install uninstall reload venv update-manager-install update-manager-uninstall lint test

venv:
	$(PYTHON) -m venv "$(VENV_DIR)"
	"$(VENV_DIR)/bin/pip" install --upgrade pip
	if [ "$(WITH_HARDWARE)" = "1" ]; then "$(VENV_DIR)/bin/pip" install -r requirements-pi.txt; else "$(VENV_DIR)/bin/pip" install -r requirements.txt; fi

install: venv
	install -d "$(DESTDIR)$(SYSTEMD_DIR)"
	install -m 644 moonblink/moonblink.service "$(DESTDIR)$(SYSTEMD_DIR)/$(SERVICE_NAME).service"
	install -d "$(DESTDIR)$(CONFIG_DIR)"
	install -m 644 config/moonblink.yaml "$(DESTDIR)$(CONFIG_DIR)/moonblink.yaml"
	if [ "$(ENABLE_UPDATE_MANAGER)" = "1" ]; then $(MAKE) update-manager-install; fi

uninstall:
	rm -f "$(DESTDIR)$(SYSTEMD_DIR)/$(SERVICE_NAME).service"
	rm -f "$(DESTDIR)$(CONFIG_DIR)/moonblink.yaml"
	if [ -z "$(DESTDIR)" ]; then rm -rf "$(VENV_DIR)"; fi
	if [ "$(ENABLE_UPDATE_MANAGER)" = "1" ]; then $(MAKE) update-manager-uninstall; fi

reload:
	systemctl daemon-reload

update-manager-install:
	install -d "$(DESTDIR)$(UPDATE_MANAGER_DIR)"
	if [ "$(WITH_HARDWARE)" = "1" ]; then req_file="requirements-pi.txt"; else req_file="requirements.txt"; fi; \
	printf '%s\n' \
		'[update_manager $(SERVICE_NAME)]' \
		'type: git_repo' \
		'path: $(REPO_PATH)' \
		'origin: $(ORIGIN)' \
		'primary_branch: $(PRIMARY_BRANCH)' \
		'virtualenv: $(REPO_PATH)/$(VENV_DIR)' \
		"requirements: $$req_file" \
		'managed_services: $(SERVICE_NAME)' \
		> "$(DESTDIR)$(UPDATE_MANAGER_DIR)/moonblink.conf"

update-manager-uninstall:
	rm -f "$(DESTDIR)$(UPDATE_MANAGER_DIR)/moonblink.conf"

test:
	$(PYTHON) -m compileall -q moonblink tests
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	ruff check moonblink tests

