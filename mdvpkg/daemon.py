##
## Copyright (C) 2010-2011 Mandriva S.A <http://www.mandriva.com>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
##
## Author(s): J. Victor Martins <jvdm@mandriva.com>
##
""" Main daemon class. """


import dbus
import mdvpkg

# setup default dbus mainloop:
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)


class MDVPKGDaemon:
    """
    Represents the daemon, which provides the dbus interface at the
    system bus.

    The daemon is responsible of managing transactions which is the
    base of package managing operations.
    """

    def __init__(self, bus=None):
        if not bus:
            bus = dbus.SystemBus()
        self._bus = bus


    @dbus.service.method(

    def start(self):
        self.interface.start()

    def stop(self):
        self.interface.stop()

    def get_repo(self):
        return self.repo

    def list_names(self, filter):
        pkgs = []
        for pkg_name in self.repo._list:
            if pkg_name.find(filter) >= 0:
                pkgs.append(pkg_name)
        return pkgs

    def install_pkg(self, pkg_name):
        print 'trying to install', pkg_name
        return self.repo.install_pkg(pkg_name);
