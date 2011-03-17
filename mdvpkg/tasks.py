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
        print 'Running ListMedias task'
        medias = backend.do('list_medias')
        for media in medias:
            self.Media(*media)


class ListGroupsTask(TaskBase):
    """ List all available groups. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='si')
    def Group(self, group, pkg_count):
        pass

    def worker_callback(self, backend):
        groups = backend.do('list_groups')
        for group in groups:
            self.Group(*group)


class ListPackagesTask(TaskBase):
    """ List all available packages. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='a{ss}bs')
    def Package(self, package_name, installed, summary):
        pass

    def worker_callback(self, backend):
        results = backend.do('list_packages')
        for result in results:
            installed = result.pop('installed')
            summary = result.pop('summary')
            self.Package(result, installed, summary)


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
        results = backend.do('package_details', name=self.name)
        for result in results:
            group = result.pop('group')
            size = result.pop('size')
            installtime = result.pop('installtime')
            media = result.pop('media')
            self.PackageDetails(result,
                                group,
                                media,
                                size,
                                installtime)


class SearchFilesTask(TaskBase):
    """ Query for package owning file paths. """

    def __init__(self, bus, sender, worker, patterns):
        TaskBase.__init__(self, bus, sender, worker)
        self.patterns = patterns
        self.regex = False

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
        self.regex = regex

    def worker_callback(self, backend):
        for pattern in self.patterns:
            opts = {'pattern': pattern}
            if self.regex:
                opts['fuzzy'] = self.regex
            results = backend.do('search_files', **opts)
            for r in results:
                self.PackageFiles(r['name'], r['version'], r['release'],
                                      r['arch'], r['files'])
