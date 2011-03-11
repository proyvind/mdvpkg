#!/bin/bash

VERSION=`python -c 'import mdvpkg; print mdvpkg.__version__'`
TARBALL=mdvpkg-$VERSION.tar
if [ -e $TARBALL.bz2 ]; then
	echo "Archive already created"
	exit 1
fi

git archive --prefix=mdvpkg-$VERSION/ --format=tar HEAD -o $TARBALL
bzip2 $TARBALL
