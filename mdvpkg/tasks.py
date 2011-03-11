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


import dbus
import dbus.service
import dbus.service
import uuid

import mdvpkg


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
                         signature='sbb')
    def Media(self, media_name, update, ignore):
        pass

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='')
    def Finished(self):
        pass

    def worker_callback(self, backend):
        """ Called by the worker to perform the task. """
        raise NotImplementedError()


class ListMediasTask(TaskBase):
    """ List all available medias. """

    def worker_callback(self, backend):
        print 'Running ListMedias task'
        medias = backend.do('list_medias')
        for media in medias:
            self.Media(*media)
        self.Finished()


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
        self.Finished()


class ListPackagesTask(TaskBase):
    """ List all available packages. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ssssssb')
    def Package(self,
                name,
                version,
                release,
                disttag,
                distepoch,
                arch,
                installed):
        pass

    def worker_callback(self, backend):
        pkgs = backend.do('list_packages')
        for pkg in pkgs:
            self.Package(*pkg)
        self.Finished()


class PackageDetailsTask(TaskBase):
    """ Query for details of a package. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='a{ss}')
    def PackageDetails(self, details_dict):
        pass

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='s',
                         out_signature='',
                         sender_keyword='sender')
    def SetName(self, name, sender):
        """ Set the package name to get details from. """
        self.name = name

    def worker_callback(self, backend):
        results = backend.do('package_details', name=self.name)
        for details in results:
            self.PackageDetails(details)
        self.Finished()
