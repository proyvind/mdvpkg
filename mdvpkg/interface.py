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
## Author(s): J. Victor Martins <jvdm@mandriva.com>
##
##
""" Package Daemon interfaces. """
       
import dbus
import dbus.service
import dbus.mainloop.glib
import gobject


dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

class DBusService(dbus.service.Object):
    """ A dbus service interface to mdvpkgd. """
    
    service_name = 'org.mandrivalinux.PackageDaemon'
    interface_name = 'org.mandrivalinux.PackageDaemon'

    def __init__(self, daemon):
        self.daemon = daemon

    def start(self):
        bus = dbus.SystemBus();
        dbus.service.Object.__init__(
            self,
            object_path='/',
            bus_name=dbus.service.BusName(self.service_name, bus)
        )

        self.loop = gobject.MainLoop()
        self.loop.run();

    def stop(self):
        self.loop.quit()

    #
    # D-Bus Service Methods
    #

    @dbus.service.method(dbus_interface=interface_name,
                         in_signature='s',
                         out_signature='b')
    def install(self, pkg_name):
        """Calls urpmi to install a package."""
        return self.daemon.install_pkg(pkg_name)

    @dbus.service.method(dbus_interface=interface_name,
                         in_signature='s',
                         out_signature='as')
    def list_names(self, filter=''):
        """Lists all package names, optionally filtering with a
        pattern."""
        return self.daemon.list_names(filter)

    @dbus.service.method(dbus_interface=interface_name,
                         in_signature='s',
                         out_signature='a{sa(ssss)}')
    def listpkgs(self, pattern):
        """Lists packages according to a pattern, returns a dictionary
        of {category: (name, summary, installed)} (uninstalled have
        installed='').
        """
        packages = {}
        pkglist = self.daemon.get_repo()._list
        for item in pkglist:
            if item.find(pattern) >= 0:
                cat = pkglist[item]['group']
                descr = pkglist[item]['summary']
                installed = pkglist[item]['installed']
                source = pkglist[item]['source']
                if installed == None:
                    installed = ''
                if cat not in packages:
                    packages[cat] = []
                packages[cat].append((item, descr, installed, source))
        return packages
