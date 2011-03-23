NAME = mdvpkg
VERSION = $(shell python -c 'import mdvpkg; print mdvpkg.__version__')
TARBALL = $(NAME)-$(VERSION).tar.bz2

ROOT = ''

DATA_DIR = $(ROOT)$(shell python -c 'import mdvpkg; '\
                                    'print mdvpkg.DEFAULT_DATA_DIR')/
DOC_DIR = $(ROOT)/usr/share/doc/mandriva/
SBIN_DIR = $(ROOT)/usr/sbin/
DBUS_DATA_DIR = $(ROOT)/usr/share/dbus-1/system-services/
DBUS_CONF_DIR = $(ROOT)/etc/dbus-1/system.d/


.PHONY: $(TARBALL) install clean 

$(TARBALL):
	@git archive --prefix=$(NAME)-$(VERSION)/ \
	    --format=tar HEAD | bzip2 > $(TARBALL)
	@echo Created tarball: $(TARBALL) $(PREFIX)

install:
	install -d $(DATA_DIR) $(SBIN_DIR) \
                        $(DBUS_DATA_DIR) $(DBUS_CONF_DIR) 
	cp -R mdvpkg/ $(DATA_DIR)
	cp -R backend/ $(DATA_DIR)
	cp -R -P doc/* $(DOC_DIR)
	install -m755 bin/mdvpkgd $(SBIN_DIR)
	install -m644 dbus/*.conf $(DBUS_CONF_DIR)
	install -m644 dbus/*.service $(DBUS_DATA_DIR)

clean:
	rm -r $(TARBALL)
