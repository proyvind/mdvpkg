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
""" Task classes and task worker for mdvpkg. """


import gobject
import dbus
import dbus.service
import dbus.service
import uuid

import mdvpkg


# Delay before removing tasks from the bus:
TASK_DEL_TIMEOUT = 5


class TaskBase(dbus.service.Object):
    """ Base class for all tasks. """

    def __init__(self, bus, sender, worker):
        self._bus = bus
        self.path = '%s/%s' % (mdvpkg.DBUS_TASK_PATH, uuid.uuid4().get_hex())
        dbus.service.Object.__init__(
            self,
            dbus.service.BusName(mdvpkg.DBUS_SERVICE, self._bus),
            self.path
            )
        self._sender = sender
        self._worker = worker

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def Run(self, sender):
        print 'Task.Run() sender=%s, task=%s' % (sender, self.path)
        self._worker.push(self)

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='')
    def Finished(self):
        pass

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def Error(self, msg):
        pass

    def worker_callback(self, backend):
        """ Called by the worker to perform the task. """
        raise NotImplementedError()

    def exit_callback(self):
        self.Finished()
        # mall timeout so the signal can propagate:
        gobject.timeout_add_seconds(TASK_DEL_TIMEOUT,
                                    self.remove_from_connection)


class ListMediasTask(TaskBase):
    """ List all available medias. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='sbb')
    def Media(self, media_name, update, ignore):
        pass

    def worker_callback(self, backend):
        (success, result) = backend.do('list_medias')
        if success:
            for media in result:
                self.Media(*media)
        else:
            self.Error(result)


class ListGroupsTask(TaskBase):
    """ List all available groups. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='si')
    def Group(self, group, pkg_count):
        pass

    def worker_callback(self, backend):
        (success, result) = backend.do('list_groups')
        if success:
            for group in result:
                self.Group(*group)
        else:
            self.Error(result)


class ListPackagesTask(TaskBase):
    """ List all available packages. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='a{ss}ss')
    def Package(self, name, summary, status):
        pass

    def worker_callback(self, backend):
        (success, result) = backend.do('list_packages')
        if success:
            for pkg in result:
                summary = pkg.pop('summary')
                status = pkg.pop('status')
                self.Package(pkg, summary, status)
        else:
            self.Error(result)


class PackageDetailsTask(TaskBase):
    """ Query for details of a package. """

    def __init__(self, bus, sender, worker, name):
        TaskBase.__init__(self, bus, sender, worker)
        self.name = name

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='a{ss}sstt')
    def PackageDetails(self, name, group, media, size, installtime):
        pass

    def worker_callback(self, backend):
        (success, result) = backend.do('package_details',
                                       name=self.name)
        if success:
            for pkg in result:
                group = pkg.pop('group')
                size = pkg.pop('size')
                installtime = pkg.pop('installtime')
                media = pkg.pop('media')
                self.PackageDetails(pkg,
                                    group,
                                    media,
                                    size,
                                    installtime)
        else:
            self.Error(result)


class SearchFilesTask(TaskBase):
    """ Query for package owning file paths. """

    def __init__(self, bus, sender, worker, pattern):
        TaskBase.__init__(self, bus, sender, worker)
        self.args = []
        self.kwargs = {'pattern': pattern}

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ssssas')
    def PackageFiles(self, name, version, release, arch, files):
        pass

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def SetRegex(self, regex, sender):
        """ Match file names using a regex. """
        self.args.append('fuzzy')

    def worker_callback(self, backend):
        (success, result) = backend.do('search_files',
                                       *self.args,
                                       **self.kwargs)
        if success:
            for r in result:
                self.PackageFiles(r['name'], r['version'], r['release'],
                                  r['arch'], r['files'])
        else:
            self.Error(result)

