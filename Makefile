PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
SHAREDIR ?= $(PREFIX)/share/moonblink
SYSTEMD_DIR ?= /etc/systemd/system
CONFIG_DIR ?= /home/pi/printer_data/config
UPDATE_MANAGER_DIR ?= /home/pi/printer_data/config/moonraker.conf.d
SERVICE_NAME ?= moonblink
PYTHON ?= python3

.PHONY: install uninstall reload update-manager-install update-manager-uninstall lint test

install:
	install -d "$(DESTDIR)$(SHAREDIR)" "$(DESTDIR)$(BINDIR)" "$(DESTDIR)$(SYSTEMD_DIR)"
	install -m 644 README.md SPEC.md AGENTS.md "$(DESTDIR)$(SHAREDIR)/"
	install -m 644 config/moonblink.yaml "$(DESTDIR)$(SHAREDIR)/moonblink.yaml"
	install -m 644 moonblink/moonblink.service "$(DESTDIR)$(SYSTEMD_DIR)/$(SERVICE_NAME).service"
	install -d "$(DESTDIR)$(CONFIG_DIR)"
	install -m 644 config/moonblink.yaml "$(DESTDIR)$(CONFIG_DIR)/moonblink.yaml"
	$(MAKE) update-manager-install

uninstall:
	rm -f "$(DESTDIR)$(SYSTEMD_DIR)/$(SERVICE_NAME).service"
	rm -rf "$(DESTDIR)$(SHAREDIR)"
	rm -f "$(DESTDIR)$(CONFIG_DIR)/moonblink.yaml"
	$(MAKE) update-manager-uninstall

reload:
	systemctl daemon-reload

update-manager-install:
	if [ -d "$(DESTDIR)$(UPDATE_MANAGER_DIR)" ]; then \
		install -d "$(DESTDIR)$(UPDATE_MANAGER_DIR)"; \
		printf '%s\n' '[moonblink]' 'path = /home/pi/moonblink' 'origin = https://github.com/arkane-systems/moonblink' > "$(DESTDIR)$(UPDATE_MANAGER_DIR)/moonblink.conf"; \
	fi

update-manager-uninstall:
	rm -f "$(DESTDIR)$(UPDATE_MANAGER_DIR)/moonblink.conf"

test:
	$(PYTHON) -m compileall -q moonblink tests
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	ruff check moonblink tests
