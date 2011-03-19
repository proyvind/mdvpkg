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


import logging
import re
import gobject
import dbus
import dbus.service
import dbus.service
import uuid

import mdvpkg
import mdvpkg.worker


# Delay before removing tasks from the bus:
TASK_DEL_TIMEOUT = 5

log = logging.getLogger("mdvpkgd.task")


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
        log.info('Task created: %s, %s',
                 self.__class__.__name__,
                 self.path)
        self._sender = sender
        self._worker = worker
        # Passed to backend when call_backend is called ...
        self.backend_args = []
        self.backend_kwargs = {}

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def Run(self, sender):
        log.info('Run method called: %s', sender)
        self._worker.push(self)

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='')
    def Finished(self):
        log.info('Finished signal emitted')
        pass

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def Error(self, msg):
        log.info('Error signal emitted: %s', msg)
        pass

    def worker_callback(self, backend):
        """ Called by the worker to perform the task. """
        raise NotImplementedError()

    def exit_callback(self):
        """ Called by the worker when the task is finished. """
        self.Finished()
        log.info('Task removed: %s', self.path)
        # mall timeout so the signal can propagate:
        gobject.timeout_add_seconds(TASK_DEL_TIMEOUT,
                                    self.remove_from_connection)

    def _backend_helper(self, backend, command):
        """
        Helper to receive call backend commands, handling backend
        errors.  It yields each backend reponse.
        """
        try:
            for l in backend.do(command,
                                *self.backend_args,
                                **self.backend_kwargs):
                yield l
        except mdvpkg.worker.BackendDoError as msg:
            log.debug('backend error: %s', msg)
            self.Error(msg.args[0])


class ListMediasTask(TaskBase):
    """ List all available medias. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='sbb')
    def Media(self, media_name, update, ignore):
        log.debug('Media signal emitted: %s', media_name)
        pass

    def worker_callback(self, backend):
        for media in self._backend_helper(backend, 'list_medias'):
            self.Media(*media)


class ListGroupsTask(TaskBase):
    """ List all available groups. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='si')
    def Group(self, group, pkg_count):
        log.debug('Group signal emitted: %s', group)
        pass

    def worker_callback(self, backend):
        for group in self._backend_helper(backend, 'list_groups'):
            self.Group(*group)


class ListPackagesTask(TaskBase):
    """ List all available packages. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='a{ss}sssst')
    def Package(self, name, epoch, status, group, summary, size):
        log.debug('Package signal emitted: %s', name)
        pass

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='s',
                         out_signature='',
                         sender_keyword='sender')
    def FilterName(self, name, sender):
        log.info('FilterName() called: %s', name)
        self.backend_kwargs['name'] = name

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='s',
                         out_signature='',
                         sender_keyword='sender')
    def FilterMedia(self, media, sender):
        log.info('FilterMedia() called: %s', media)
        self.backend_kwargs['media'] = media

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='s',
                         out_signature='',
                         sender_keyword='sender')
    def FilterGroup(self, group, sender):
        log.info('FilterGroup() called: %s', group)
        self.backend_kwargs['group'] = group

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='s',
                         out_signature='',
                         sender_keyword='sender')
    def FilterStatus(self, filter, sender):
        log.info('FilterStatus() called: %s', filter)
        if not re.match('~?(new|upgrade|local)', filter):
            self.Error('Unknow status filter: %s' % filter)
            self.exit_callback()
        else:
            self.backend_args.append(filter)

    def worker_callback(self, backend):
        for pkg in self._backend_helper(backend, 'list_packages'):
            epoch = pkg.pop('epoch')
            group = pkg.pop('group')
            summary = pkg.pop('summary')
            status = pkg.pop('status')
            size = pkg.pop('size')
            self.Package(pkg, epoch, status, group, summary, size)


class PackageDetailsTask(TaskBase):
    """ Query for details of a package. """

    def __init__(self, bus, sender, worker, name):
        TaskBase.__init__(self, bus, sender, worker)
        self.backend_kwargs['name'] = name

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='a{ss}st')
    def PackageDetails(self, name, media, installtime):
        log.debug('PackageDetails signal emitted: %s', name)
        pass

    def worker_callback(self, backend):
        for pkg in self._backend_helper(backend, 'package_details'):
            media = pkg.pop('media')
            installtime = pkg.pop('installtime')
            self.PackageDetails(pkg, media, installtime)


class SearchFilesTask(TaskBase):
    """ Query for package owning file paths. """

    def __init__(self, bus, sender, worker, pattern):
        TaskBase.__init__(self, bus, sender, worker)
        self.backend_kwargs['pattern'] = pattern

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ssssas')
    def PackageFiles(self, name, version, release, arch, files):
        log.debug('PackageFiles signal emitted: %s, %s', name, files)
        pass

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def SetRegex(self, regex, sender):
        log.info('SetRegex() called: %s', regex)
        """ Match file names using a regex. """
        self.args.append('fuzzy')

    def worker_callback(self, backend):
        for r in self._backend_helper(backend, 'search_files'):
            self.PackageFiles(r['name'], r['version'], r['release'],
                                  r['arch'], r['files'])
