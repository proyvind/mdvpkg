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


import logging
import logging.handlers
import sys
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import gobject
import signal 

import mdvpkg
import mdvpkg.exceptions
import mdvpkg.tasks
import mdvpkg.worker


# setup default dbus mainloop:
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

# setup logging ...
log = logging.getLogger("mdvpkgd")
try:
    _syslog = logging.handlers.SysLogHandler(
                  address="/dev/log",
                  facility=logging.handlers.SysLogHandler.LOG_DAEMON
              )
    _syslog.setLevel(logging.INFO)
    _formatter = logging.Formatter("%(name)s: %(levelname)s: "
                                       "%(message)s")
    _syslog.setFormatter(_formatter)
except:
    pass
else:
    log.addHandler(_syslog)

_console = logging.StreamHandler()
_formatter = logging.Formatter("%(asctime)s %(name)s [%(levelname)s]: "
                                   "%(message)s",
                               "%T")
_console.setFormatter(_formatter)
log.addHandler(_console)

IDLE_CHECK_INTERVAL = 1000
IDLE_TIMEOUT = 5 * 60


class MDVPKGDaemon(dbus.service.Object):
    """
    Represents the daemon, which provides the dbus interface (by
    default at the system bus).

    The daemon is responsible of managing transactions which is the
    base of package managing operations.
    """

    def __init__(self, bus=None, backend_path=None):
        log.info('Starting daemon')

        signal.signal(signal.SIGQUIT, self._quit_handler)
        signal.signal(signal.SIGTERM, self._quit_handler)

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
            log.critical('Someone is using %s service name...',
                         mdvpkg.DBUS_SERVICE)
            sys.exit(1)
        dbus.service.Object.__init__(self, bus_name, mdvpkg.DBUS_PATH)
        self._worker = mdvpkg.worker.TaskWorker(backend_path)
        gobject.timeout_add(IDLE_CHECK_INTERVAL, self._check_for_inactivity)

    def run(self):
        try:
            self._loop.run()
        except KeyboardInterrupt:
            self.Quit(None)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='',
                         out_signature='s',
                         sender_keyword='sender')
    def ListMedias(self, sender):
        log.info('ListMedias() called')
        return self._create_task(mdvpkg.tasks.ListMediasTask,
                                 sender)
        
    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='',
                         out_signature='s',
                         sender_keyword='sender')
    def ListGroups(self, sender):
        log.info('ListGroups() called')
        return self._create_task(mdvpkg.tasks.ListGroupsTask,
                                 sender)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='',
                         out_signature='s',
                         sender_keyword='sender')
    def ListPackages(self, sender):
        log.info('ListPackages() called')
        return self._create_task(mdvpkg.tasks.ListPackagesTask,
                                 sender)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='s',
                         out_signature='s',
                         sender_keyword='sender')
    def PackageDetails(self, name, sender):
        log.info('PackageDetails() called: %s', name)
        return self._create_task(mdvpkg.tasks.PackageDetailsTask,
                                 sender,
                                 name)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature='as',
                         out_signature='s',
                         sender_keyword='sender')
    def SearchFiles(self, files, sender):
        log.info('SearchFiles() called: %s', files)
        return self._create_task(mdvpkg.tasks.SearchFilesTask,
                                 sender,
                                 files)

    @dbus.service.method(mdvpkg.DBUS_INTERFACE,
                         in_signature="",
                         out_signature="",
                         sender_keyword="sender")
    def Quit(self, sender):
        """ Request a shutdown of the service. """
        log.info("Shutdown was requested")
        log.debug("Quitting main loop...")
        self._loop.quit()
        log.debug("Terminating worker...")
        self._worker.stop()

    def _create_task(self, task_class, sender, *args):
        log.debug('_create_task(): %s, %s, args=%s',
                  task_class.__name__,
                  sender,
                  args)
        task = task_class(self._bus, sender, self._worker, *args)
        return task.path

    def _quit_handler(self, signum, frame):
        """ Handler for quiting signals. """
        self.Quit(None)

    def _check_for_inactivity(self):
        """
        Shutdown the daemon if it has been inactive for time specified
        in IDLE_TIMEOUT.
        """
        log.debug("Checking for inactivity")
        if self._worker.inactive(IDLE_TIMEOUT) \
               and not gobject.main_context_default().pending():
            log.info("Quiting due to inactivity")
            self.Quit(None)
            return False
        return True
