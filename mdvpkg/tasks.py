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
import gobject
import dbus
import dbus.service
import dbus.service
import uuid

import mdvpkg
import mdvpkg.worker
import mdvpkg.exceptions


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
        self._sender = sender
        self._worker = worker
        # Passed to backend when call_backend is called ...
        self.backend_args = []
        self.backend_kwargs = {}
        # If the task was already sent to the worker:
        self._queued = False
        # Watch for sender (which is a unique name) changes:
        self._sender_watch = self._bus.watch_name_owner(
                                     self._sender,
                                     self._sender_owner_changed
                                 )
        log.debug('Task created: %s, %s', self._sender, self.path)

    #
    # D-Bus Interface
    #

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def Run(self, sender):
        """ Run the task. """
        self._check_same_user(sender)
        log.debug('Run method called: %s, %s', sender, self.path)
        if self._queued:
            raise mdvpkg.exceptions.TaskAlreadyRunning()
        self._queued = True
        self._worker.push(self)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def Cancel(self, sender):
        """ Cancel and remove the task. """
        self._check_same_user(sender)
        log.debug('Cancel method called: %s, %s', sender, self.path)
        self._cancel()

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='')
    def Finished(self):
        """ Signals that the task has finished successfully. """
        log.debug('Finished signal emitted: %s', self.path)
        pass

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def Error(self, msg):
        """ Signals a task error during running. """
        log.debug('Error signal emitted: %s (%s)',
                  self.path,
                  msg)
        pass

    #
    # Worker Callbacks
    #

    def worker_callback(self, urpmi, backend):
        """ Called by the worker to perform the task. """
        raise NotImplementedError()

    def exit_callback(self):
        """ Called by the worker when the task is finished. """
        self.Finished()
        self._remove_and_cleanup()

    #
    # Private and helpers
    #

    def _cancel(self):
        if self._queued:
            self._worker.cancel(self)
            self._queued = False
        self._remove_and_cleanup()

    def _remove_and_cleanup(self):
        """ Remove the task from the bus and clean up. """
        self._sender_watch.cancel()
        # Small timeout so the signal can propagate:
        gobject.timeout_add_seconds(TASK_DEL_TIMEOUT,
                                    self.remove_from_connection)
        log.debug('Task removed: %s', self.path)

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
            log.debug('Backend error: %s', msg)
            self.Error(msg.args[0])

    def _sender_owner_changed(self, connection):
        """ Called when the sender owner changes. """
        # Since we are watching a unique name this will be only called
        # when the name is acquired and when the name is released; the
        # latter will have connection == None:
        if not connection:
            log.debug('Sender disconnected: %s, %s',
                      self._sender,
                      self.path)
            self._cancel()

    def _check_same_user(self, sender):
        """ Check if the sender is the same that created the task. """
        if self._sender != sender:
            raise mdvpkg.exceptions.NotOwner()


class ListMediasTask(TaskBase):
    """ List all available medias. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='sbb')
    def Media(self, media_name, update, ignore):
        log.debug('Media signal emitted: %s', media_name)
        pass

    def worker_callback(self, urpmi, backend):
        for media in urpmi.medias.values():
            self.Media(media.name, media.update, media.ignore)


class ListGroupsTask(TaskBase):
    """ List all available groups. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='st')
    def Group(self, group, count):
        log.debug('Group signal emitted: %s', group)

    def worker_callback(self, urpmi, backend):
        for (group, count) in urpmi.groups.items():
            self.Group(group, count)


class ListPackagesTask(TaskBase):
    """ List all available packages. """

    def __init__(self, *args):
        TaskBase.__init__(self, *args)
        self.filters = {'name': {'sets': {},
                                 'match_func': self._match_name},
                        'media': {'sets': {},
                                  'match_func': self._match_media},
                        'group': {'sets': {},
                                  'match_func': self._match_group},
                        'status': {'sets': {},
                                   'match_func': self._match_status},}
        self.details = []

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='(ssss)(sssstt)bb')
    def Package(self, nvra, details, upgrades, downgrades):
        log.debug('Package signal emitted: %s', nvra)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterName(self, names, exclude, sender):
        self._check_same_user(sender)
        log.debug('FilterName() called: %s', names)
        self._append_or_create_filter('name', exclude, names)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterMedia(self, medias, exclude, sender):
        self._check_same_user(sender)
        log.debug('FilterMedia() called: %s', medias)
        self._append_or_create_filter('media', exclude, medias)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterGroup(self, groups, exclude, sender):
        self._check_same_user(sender)
        log.debug('FilterGroup() called: %s', groups)
        self._append_or_create_filter('group', exclude, groups)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterUpgrade(self, exclude, sender):
        self._check_same_user(sender)
        log.debug('FilterStatus() called: %s', exclude)
        self._append_or_create_filter('status', exclude, ['upgrade'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterDowngrade(self, exclude, sender):
        self._check_same_user(sender)
        log.debug('FilterStatus() called: %s', exclude)
        self._append_or_create_filter('status', exclude, ['downgrade'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterNew(self, exclude, sender):
        self._check_same_user(sender)
        log.debug('FilterStatus() called: %s', exclude)
        self._append_or_create_filter('status', exclude, ['new'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterInstalled(self, exclude, sender):
        self._check_same_user(sender)
        log.debug('FilterStatus() called: %s', exclude)
        self._append_or_create_filter('status', exclude, ['current'])

    def _append_or_create_filter(self, filter_name, exclude, data):
        """ 
        Append more data to the filter set (selected by exclude flag),
        or create and initialize the set if it didn't existed.
        """
        sets = self.filters[filter_name]['sets']
        _set = sets.get(exclude)
        if not _set:
            _set = set()
            sets[exclude] = _set
        _set.update(data)

    #
    # Filter Callbacks
    #

    def _match_name(self, candidate, patterns):
        for pattern in patterns:
            if candidate.find(pattern) != -1:
                return True
        return False

    def _match_media(self, media, medias):
        return media in medias

    def _match_group(self, group, groups):
        folders = group.split('/')
        for i in range(1, len(folders) + 1):
            if '/'.join(folders[:i]) in groups:
                return True
        return False

    def _match_status(self, pkg, statuses):
        if 'upgrade' in statuses and pkg.upgrades:
            return True
        if 'downgrade' in statuses and pkg.downgrades:
            return True
        return pkg.status in statuses

    def _is_filtered(self, candidate, filter_name):
        """
        Check if candidate should be filtered by the rules of filter
        filter_name.
        """
        match_func = self.filters[filter_name]['match_func']
        for (exclude, data) in self.filters[filter_name]['sets'].items():
            if exclude ^ (not match_func(candidate, data)):
                return True
        return False

    def worker_callback(self, urpmi, backend):
        for p in urpmi.packages:
            if self._is_filtered(p.name, 'name') \
                    or self._is_filtered(p, 'status'):
                continue
            for version in p.versions:
                rpm = version['rpm']
                media = version['media']
                if self._is_filtered(media, 'media') \
                        or self._is_filtered(rpm.group, 'group'):
                    continue
                installtime = str()
                self.Package(
                    (rpm.name, rpm.version, rpm.release, rpm.arch),
                    (p.status,
                     media,
                     rpm.group,
                     rpm.summary,
                     rpm.size,
                     version.get('installtime', 0)),
                    bool(p.upgrades),
                    bool(p.downgrades)
                )


class PackageDetailsTask(TaskBase):
    """ Query for details of a package. """

    def __init__(self, bus, sender, worker, nvra):
        TaskBase.__init__(self, bus, sender, worker)
        self.nvra = nvra

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='(ssss)sstt')
    def PackageDetails(self, nvra, group, summary, size, installtime):
        log.debug('PackageDetails signal emitted: %s', nvra)

    def worker_callback(self, urpmi, backend):
        pass


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
        self._check_same_user(sender)
        log.debug('SetRegex() called: %s', regex)
        """ Match file names using a regex. """
        self.args.append('fuzzy')

    def worker_callback(self, urpmi, backend):
        for r in self._backend_helper(backend, 'search_files'):
            self.PackageFiles(r['name'], r['version'], r['release'],
                                  r['arch'], r['files'])
