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

## Finish status
EXIT_SUCCESS = 'exit-success'
EXIT_FAILED = 'exit-failed'
EXIT_CANCELLED = 'exit-cancelled'

## Error status
ERROR_TASK_EXCEPTION = 'error-task-exception'

## Task status
# The task is being setup
STATUS_SETTING_UP = 'status-setting-up'
# Run() has just been called
STATUS_RUNNING = 'status-running'
# The task runner has finished
STATUS_READY = 'status-ready'

log = logging.getLogger("mdvpkgd.task")


class TaskBase(dbus.service.Object):
    """ Base class for all tasks. """

    def __init__(self, daemon, sender):
        self._bus = daemon.bus
        self.path = '%s/%s' % (mdvpkg.DBUS_TASK_PATH, uuid.uuid4().get_hex())
        dbus.service.Object.__init__(
            self,
            dbus.service.BusName(mdvpkg.DBUS_SERVICE, self._bus),
            self.path
            )
        self.urpmi = daemon.urpmi
        self.backend = daemon.backend
        self.cancelled = False
        self._sender = sender
        self._status = STATUS_SETTING_UP

        # Passed to backend when call_backend is called ...
        self.backend_args = []
        self.backend_kwargs = {}

        # Watch for sender (which is a unique name) changes:
        self._sender_watch = self._bus.watch_name_owner(
                                     self._sender,
                                     self._sender_owner_changed
                                 )
        log.debug('Task created: %s, %s', self._sender, self.path)

    @property
    def status(self):
        """ Task status. """
        return self._status

    @status.setter
    def status(self, status):
        self._status = status
        self.StatusChanged(status)

    #
    # D-Bus Interface
    #

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def Run(self, sender):
        """ Run the task. """
        log.debug('Run called: %s, %s', sender, self.path)
        self._check_same_user(sender)
        self.status = STATUS_RUNNING
        self._run()

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def Cancel(self, sender):
        """ Cancel and remove the task. """
        log.debug('Cancel called: %s, %s', sender, self.path)
        self._check_same_user(sender)
        self.cancel()

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def Finished(self, status):
        """ Signals that the task has finished successfully. """
        log.debug('Finished emitted: %s %s', self.path, status)

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ss')
    def Error(self, status, message):
        """ Signals a task error during running. """
        log.debug('Error emitted: %s, %s, %s',
                  self.path,
                  status,
                  message)

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def StatusChanged(self, status):
        """ Signals the task status has changed. """
        log.debug('StatusChanged emitted: %s, %s',
                  self.path,
                  status)

    def run(self):
        """ Default runner, must be implemented in childs. """
        raise NotImplementedError()

    def cancel(self):
        self.cancelled = True
        if self.status == STATUS_SETTING_UP:
            self.Finished(EXIT_CANCELLED)
            self._remove_and_cleanup()

    def _run(self):
        """ Controls the co-routine running the task. """
        def step(gen):
            try:
                gen.next()
                if self.cancelled:
                    gen.close()
                    self.Finished(EXIT_CANCELLED)
                    self._remove_and_cleanup()
                else:
                    gobject.idle_add(step, gen)
            except StopIteration:
                self.status = STATUS_READY
                self.Finished(EXIT_SUCCESS)
                self._remove_and_cleanup()
            except Exception as e:
                self.Error(ERROR_TASK_EXCEPTION, e.message)
                self.Finished(EXIT_FAILED)
                self._remove_and_cleanup
        gobject.idle_add(step, self.run())

    def _remove_and_cleanup(self):
        """ Remove the task from the bus and clean up. """
        self._sender_watch.cancel()
        self.remove_from_connection()
        log.debug('Task removed: %s', self.path)

    ## FIXME Temporarly remove the backend helper some task needs it.
    # def _backend_helper(self, backend, command):
    #     """ Helper to receive call backend commands, handling backend
    #     errors.  It yields each backend reponse.
    #     """
    #     try:
    #         for l in backend.do(command,
    #                             *self.backend_args,
    #                             **self.backend_kwargs):
    #             yield l
    #     except mdvpkg.worker.BackendDoError as msg:
    #         log.debug('Backend error: %s', msg)
    #         self.Error(msg.args[0])

    def _sender_owner_changed(self, connection):
        """ Called when the sender owner changes. """
        # Since we are watching a unique name this will be only called
        # when the name is acquired and when the name is released; the
        # latter will have connection == None:
        if not connection:
            log.debug('Sender disconnected: %s, %s',
                      self._sender,
                      self.path)
            self.cancel()

    def _check_same_user(self, sender):
        """ Check if the sender is the task owner created the task. """
        if self._sender != sender:
            raise mdvpkg.exceptions.NotOwner()


class ListMediasTask(TaskBase):
    """ List all available medias. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='sbb')
    def Media(self, media_name, update, ignore):
        log.debug('Media emitted: %s', media_name)

    def run(self):
        for media in self.urpmi.medias.values():
            self.Media(media.name, media.update, media.ignore)
            yield


class ListGroupsTask(TaskBase):
    """ List all available groups. """

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='st')
    def Group(self, group, count):
        log.debug('Group emitted: %s', group)

    def run(self):
        for (group, count) in self.urpmi.groups.items():
            self.Group(group, count)
            yield


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
        log.debug('Package emitted: %s', nvra)

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

    def run(self):
        for p in self.urpmi.packages:
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
                yield


class PackageDetailsTask(TaskBase):
    """ Query for details of a package. """

    def __init__(self, daemon, sender, nvra):
        TaskBase.__init__(self, daemon, snder)
        self.nvra = nvra

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='(ssss)sstt')
    def PackageDetails(self, nvra, group, summary, size, installtime):
        log.debug('PackageDetails emitted: %s', nvra)

    def run(self):
        yield


class SearchFilesTask(TaskBase):
    """ Query for package owning file paths. """

    def __init__(self, daemon, sender, pattern):
        TaskBase.__init__(self, daemon, sender)
        self.backend_kwargs['pattern'] = pattern

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ssssas')
    def PackageFiles(self, name, version, release, arch, files):
        log.debug('PackageFiles emitted: %s, %s', name, files)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def SetRegex(self, regex, sender):
        self._check_same_user(sender)
        log.debug('SetRegex() called: %s', regex)
        """ Match file names using a regex. """
        self.args.append('fuzzy')

    def run(self):
        for r in self._backend_helper(backend, 'search_files'):
            self.PackageFiles(r['name'], r['version'], r['release'],
                                  r['arch'], r['files'])
            yield
