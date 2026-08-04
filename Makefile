SYSTEMD_DIR ?= /etc/systemd/system
CONFIG_DIR ?= /home/pi/printer_data/config
UPDATE_MANAGER_DIR ?= /home/pi/printer_data/config/moonraker.conf.d
SERVICE_NAME ?= moonblink
PYTHON ?= python3
# Update Manager registration is optional per AGENTS.md -- it is never run
# implicitly by `install`. Pass ENABLE_UPDATE_MANAGER=1 to `make install`,
# or run `make update-manager-install` explicitly, to opt in.
ENABLE_UPDATE_MANAGER ?= 0

.PHONY: install uninstall reload update-manager-install update-manager-uninstall lint test

install:
	install -d "$(DESTDIR)$(SYSTEMD_DIR)"
	install -m 644 moonblink/moonblink.service "$(DESTDIR)$(SYSTEMD_DIR)/$(SERVICE_NAME).service"
	install -d "$(DESTDIR)$(CONFIG_DIR)"
	install -m 644 config/moonblink.yaml "$(DESTDIR)$(CONFIG_DIR)/moonblink.yaml"
	if [ "$(ENABLE_UPDATE_MANAGER)" = "1" ]; then $(MAKE) update-manager-install; fi

uninstall:
	rm -f "$(DESTDIR)$(SYSTEMD_DIR)/$(SERVICE_NAME).service"
	rm -f "$(DESTDIR)$(CONFIG_DIR)/moonblink.yaml"
	if [ "$(ENABLE_UPDATE_MANAGER)" = "1" ]; then $(MAKE) update-manager-uninstall; fi

reload:
	systemctl daemon-reload

update-manager-install:
	install -d "$(DESTDIR)$(UPDATE_MANAGER_DIR)"
	printf '%s\n' '[moonblink]' 'path = /home/pi/moonblink' 'origin = https://github.com/arkane-systems/moonblink' > "$(DESTDIR)$(UPDATE_MANAGER_DIR)/moonblink.conf"

update-manager-uninstall:
	rm -f "$(DESTDIR)$(UPDATE_MANAGER_DIR)/moonblink.conf"

test:
	$(PYTHON) -m compileall -q moonblink tests
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	ruff check moonblink tests

