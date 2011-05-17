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
# The task runner has finished
STATUS_READY = 'status-ready'
# The task is Searching packages
STATUS_SEARCHING = 'status-searching'
# Task is resolving dependencies of packages
STATUS_SOLVING = 'status-resolving'
# Task is downloading packages
STATUS_DOWNLOADING = 'status-downloading'
# Task is installing packages
STATUS_INSTALLING = 'status-installing'

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
        self._check_if_has_run()
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

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='(ssss)a{sv}')
    def PackageDetails(self, nvra, details):
        log.debug('PackageDetails emitted: %s', nvra)

    def run(self):
        """ Default runner, must be implemented in childs. """
        raise NotImplementedError()

    def cancel(self):
        self.cancelled = True
        if self.status == STATUS_SETTING_UP \
                or self.status == STATUS_READY:
            self.Finished(EXIT_CANCELLED)
            self._remove_and_cleanup()
        raise Exception, 'Task already running.'

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
                self._on_ready()
            except Exception as e:
                self.Error(ERROR_TASK_EXCEPTION, e.message)
                self.Finished(EXIT_FAILED)
                self._remove_and_cleanup
        gobject.idle_add(step, self.run())

    def _on_ready(self):
        self.Finished(EXIT_SUCCESS)
        self._remove_and_cleanup()

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
            # FIXME Tasks running in the backend should be cancelled!
            self._remove_and_cleanup()

    def _check_same_user(self, sender):
        """ Check if the sender is the task owner created the task. """
        if self._sender != sender:
            raise mdvpkg.exceptions.NotOwner()

    def _check_if_has_run(self):
        """ Check if Run() has been called. """
        if self.status != STATUS_SETTING_UP:
            log.info('Task has already been run')
            raise mdvpkg.exceptions.TaskBadState


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
        self._cached = False
        self._pkg_cache = []

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='(ssss)ss(bb)')
    def Package(self, nvra, description, status, updates):
        log.debug('Package emitted: %s', nvra)

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='t')
    def Ready(self, total_of_matches):
        log.debug('Ready emitted: %s', total_of_matches)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterName(self, names, exclude, sender):
        log.debug('FilterName() called: %s', names)
        self._check_same_user(sender)
        self._check_if_has_run()
        self._append_or_create_filter('name', exclude, names)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterMedia(self, medias, exclude, sender):
        log.debug('FilterMedia() called: %s', medias)
        self._check_same_user(sender)
        self._check_if_has_run()
        self._append_or_create_filter('media', exclude, medias)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterGroup(self, groups, exclude, sender):
        log.debug('FilterGroup() called: %s', groups)
        self._check_same_user(sender)
        self._check_if_has_run()
        self._append_or_create_filter('group', exclude, groups)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterUpgrade(self, exclude, sender):
        log.debug('FilterUpgrade() called: %s', exclude)
        self._check_same_user(sender)
        self._check_if_has_run()
        self._append_or_create_filter('status', exclude, ['upgrade'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterDowngrade(self, exclude, sender):
        log.debug('FilterDowngrade() called: %s', exclude)
        self._check_same_user(sender)
        self._check_if_has_run()
        self._append_or_create_filter('status', exclude, ['downgrade'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterNew(self, exclude, sender):
        log.debug('FilterNew() called: %s', exclude)
        self._check_same_user(sender)
        self._check_if_has_run()
        self._append_or_create_filter('status', exclude, ['new'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='b',
                         out_signature='',
                         sender_keyword='sender')
    def FilterInstalled(self, exclude, sender):
        log.debug('FilterInstalled() called: %s', exclude)
        self._check_same_user(sender)
        self._check_if_has_run()
        self._append_or_create_filter('status', exclude, ['current'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='t',
                         out_signature='',
                         sender_keyword='sender')
    def Get(self, index, sender):
        log.debug('Get() called')
        self._check_same_user(sender)
        if self.status != STATUS_READY:
            raise mdvpkg.exceptions.TaskBadState
        (pkg, version) = self._pkg_cache[index]
        self._emit_package(pkg, version['rpm'])

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='t',
                         out_signature='',
                         sender_keyword='sender')
    def GetDetails(self, index, sender):
        log.debug('Get() called')
        self._check_same_user(sender)
        if self.status != STATUS_READY:
            raise mdvpkg.exceptions.TaskBadState
        (pkg, version) = self._pkg_cache[index]
        rpm = version['rpm']
        self.PackageDetails(
            (rpm.name, rpm.version, rpm.release, rpm.arch),
            { 'status': pkg.status,
              'media': version['media'],
              'installtime': version.get('installtime', 0),
              'size': rpm.size,
              'group': rpm.group,
              'summary': rpm.summary,
              'has_upgrades': bool(pkg.upgrades),
              'has_downgrades': bool(pkg.downgrades) }
        )

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='sb',
                         out_signature='',
                         sender_keyword='sender')
    def Sort(self, key, reverse, sender):
        """ Sort the a cached resulls with key. """
        log.debug('Sort() called: %s', key)
        self._check_same_user(sender)
        if self.status != STATUS_READY:
            raise mdvpkg.exceptions.TaskBadState
        if key in {'media', 'installtime'}:
            key_func = lambda pkg: pkg[1][key]
        elif key in {'status'}:
            key_func = lambda pkg: getattr(pkg[0], key)
        else:
            key_func = lambda pkg: getattr(pkg[1]['rpm'], key)
        self._pkg_cache.sort(key=key_func, reverse=reverse)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def SetCached(self, sender):
        """ 
        Set ListPackage to hold results in cache.
        
        The task will be removed from bus only if sender call
        Release() or inactive.
        """
        log.debug('SetCached() called')
        self._check_same_user(sender)
        self._check_if_has_run()
        self._cached = True

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
                if self._cached:
                    self._pkg_cache.append((p, version))
                else:
                    self._emit_package(p, rpm)
                yield

    def _on_ready(self):
        if self._cached:
            self.Ready(len(self._pkg_cache))
        else:
            TaskBase._on_ready(self)

    def _emit_package(self, pkg, rpm):
        self.Package((rpm.name, rpm.version, rpm.release, rpm.arch),
                     rpm.summary,
                     pkg.status,
                     (bool(pkg.upgrades), bool(pkg.downgrades)))

    #
    # Filter callbacks and helpers
    #

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


class PackageDetailsTask(TaskBase):
    """ Query for details of a package. """

    def __init__(self, daemon, sender, nvra):
        TaskBase.__init__(self, daemon, snder)
        self.nvra = nvra

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

class InstallPackagesTask(TaskBase):
    """ Install packages or upgrades by name. """

    def __init__(self, daemon, sender, names):
        TaskBase.__init__(self, daemon, sender)
        self.names = names

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def PreparingStart(self, total):
        log.debug('PreparingStart emitted: %s' % (total))

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ss')
    def Preparing(self, amount, total):
        log.debug('Preparing emitted: %s, %s' % (amount, total))

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='')
    def PreparingDone(self):
        log.debug('PreparingDone emitted')

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def DownloadStart(self, name):
        log.debug('DownloadStart emitted: %s' % (name))

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='sssss')
    def Download(self, name, percent, total, eta, speed):
        log.debug('Download emitted: %s, %s, %s, %s, %s'
                  % (name, percent, total, eta, speed))

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='s')
    def DownloadDone(self, name):
        log.debug('DownloadDone emitted: %s' % (name))

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ss')
    def DownloadError(self, name, message):
        log.debug('DownloadError emitted: %s' % (name, message))

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='ss')
    def InstallStart(self, name, total):
        log.debug('InstallStart emitted: %s, %s' % (name, total))

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='sss')
    def Install(self, name, amount, total):
        log.debug('Install emitted: %s, %s, %s' % (name, amount, total))

    def run(self):
        try:
            self.backend.install_packages(self, self.names)
            while not self.backend.task_has_done():
                yield
            # TODO Ask daemon to update it's cache ...  something like
            #      daemon.update_cache()
        except GeneratorExit:
            self.backend.cancel(self)
