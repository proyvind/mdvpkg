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


import sys
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import gobject

import mdvpkg
import mdvpkg.exceptions
import mdvpkg.tasks
import mdvpkg.worker


# setup default dbus mainloop:
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)


class MDVPKGDaemon(dbus.service.Object):
    """
    Represents the daemon, which provides the dbus interface (by
    default at the system bus).

    The daemon is responsible of managing transactions which is the
    base of package managing operations.
    """

    def __init__(self, bus=None, backend_path=None):
        if not bus:
            bus = dbus.SystemBus()
        self._bus = bus
        if not backend_path:
            backend_path = mdvpkg.DEFAULT_BACKEND_PATH
        self._loop = gobject.MainLoop()
        try:
            bus_name = dbus.service.BusName(mdvpkg.DBUS_SERVICE,
                                            self._bus,
                                            do_not_queue=True)
        except dbus.exceptions.NameExistsException:
            print 'Someone is using %s service name...' % mdvpkg.DBUS_SERVICE
            sys.exit(1)
        dbus.service.Object.__init__(self, bus_name, mdvpkg.DBUS_PATH)
        self._worker = mdvpkg.worker.TaskWorker(backend_path)

    def run(self):
        self._loop.run()

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='',
                         out_signature='s',
                         sender_keyword='sender')
    def ListMedias(self, sender):
        return self._create_task(mdvpkg.tasks.ListMediasTask,
                                 sender)
        
    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='',
                         out_signature='s',
                         sender_keyword='sender')
    def ListGroups(self, sender):
        return self._create_task(mdvpkg.tasks.ListGroupsTask,
                                 sender)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='',
                         out_signature='s',
                         sender_keyword='sender')
    def ListPackages(self, sender):
        return self._create_task(mdvpkg.tasks.ListPackagesTask,
                                 sender)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='s',
                         out_signature='s',
                         sender_keyword='sender')
    def PackageDetails(self, name, sender):
        return self._create_task(mdvpkg.tasks.PackageDetailsTask,
                                 sender,
                                 name)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='as',
                         out_signature='s',
                         sender_keyword='sender')
    def SearchFiles(self, files, sender):
        return self._create_task(mdvpkg.tasks.SearchFilesTask,
                                 sender,
                                 files)

    def _create_task(self, task_class, sender, *args):
        print 'Request task: %s, %s' % (task_class.__name__, sender)
        task = task_class(self._bus, sender, self._worker, *args)
        return task.path
