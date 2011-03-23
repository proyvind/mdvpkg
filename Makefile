NAME = mdvpkg
VERSION = $(shell python -c 'import mdvpkg; print mdvpkg.__version__')
SRCDIR = $(NAME)-$(VERSION)
DISTDIR = dist
TARBALL = $(DISTDIR)/$(SRCDIR).tar.bz2


.PHONY: all release clean

all: $(TARBALL)
$(TARBALL):
	@echo 'Creating tarball' $(TARBALL)
	@mkdir -p $(DISTDIR)/
	@git archive --prefix=$(SRCDIR)/ --format=tar HEAD | bzip2 > $(TARBALL)

clean:
	[ -d $(DISTDIR) ] && rm -r $(DISTDIR)
