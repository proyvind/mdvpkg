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
        log.info('Task created: %s, %s',
                 self._sender,
                 self.path)

    #
    # D-Bus Interface
    #

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='',
                         out_signature='',
                         sender_keyword='sender')
    def Run(self, sender):
        """ Run the task. """
        log.info('Run method called: %s, %s', sender, self.path)
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
        log.debug('Cancel method called: %s, %s', sender, self.path)
        if self._queued:
            self._worker.cancel(self)
            self._queued = False
        self._remove_and_cleanup()

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

    def _remove_and_cleanup(self):
        """ Remove the task from the bus and clean up. """
        self._sender_watch.cancel()
        # Small timeout so the signal can propagate:
        gobject.timeout_add_seconds(TASK_DEL_TIMEOUT,
                                    self.remove_from_connection)
        log.info('Task removed: %s', self.path)

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
            self.Cancel(None)


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
                         signature='s')
    def Group(self, group):
        log.debug('Group signal emitted: %s', group)
        pass

    def worker_callback(self, urpmi, backend):
        for group in urpmi._groups:
            self.Group(group)


class ListPackagesTask(TaskBase):
    """ List all available packages. """

    def __init__(self, *args):
        TaskBase.__init__(self, *args)
        self.filters = {}

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='(ssss)ss')
    def Package(self, nvra, versions, status):
        log.debug('Package signal emitted: %s', nvra)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterName(self, names, exclude, sender):
        log.info('FilterName() called: %s', names)
        self._add_filter('name', exclude, names)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterMedia(self, medias, exclude, sender):
        log.info('FilterMedia() called: %s', medias)
        self._add_filter('media', exclude, medias)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterGroup(self, groups, exclude, sender):
        log.info('FilterGroup() called: %s', groups)
        self._add_filter('group', exclude, groups)

    @dbus.service.method(mdvpkg.DBUS_TASK_INTERFACE,
                         in_signature='asb',
                         out_signature='',
                         sender_keyword='sender')
    def FilterStatus(self, statuses, exclude, sender):
        log.info('FilterStatus() called: %s', statuses)
        self._add_filter('status', exclude, statuses)

    def _get_latest(self, entry):
        pkg_desc = sorted(entry.values())[-1]
        return (pkg_desc['pkg'], pkg_desc['media'])

    def _add_filter(self, name, exclude, terms):
        """ Add a filter to the filters set list. """
        filter_sets = self.filters.get(name, {True: set(), False: set()})
        if name not in self.filters:
            self.filters[name] = filter_sets
        filter_sets[exclude].update(terms)

    def _data_pass_filters(self, **kwargs):
        """ 
        Get, for each filter, a candidate value from kwargs (keyed by
        filter name) and returns if the value pass the filter.
        Candidates values passes according to their presence in the
        filter's sets (True -> exclude set, False -> include set).
        """
        for (filter_name, filter_sets) in self.filters.items():
            candidate = kwargs.get(filter_name)
            if candidate is None:
                raise KeyError, \
                    "Missing candidate for filter '%s'" % filter_name
            for (exclude, _set) in filter_sets.items():
                if _set and exclude ^ (candidate not in _set):
                        return False
        return True

    def worker_callback(self, urpmi, backend):
        for entry in urpmi._cache.values():
            for status in ('new', 'upgrade', 'current'):
                desc = entry.get(status)
                if desc:
                    break
            for (pkg, media) in [(d['pkg'], d['media'])
                                 for d in desc.values()]:
                if self._data_pass_filters(name=pkg.name,
                                           group=pkg.group,
                                           media=media, 
                                           status=status):
                    self.Package((pkg.name, pkg.version, 
                                      pkg.release, pkg.arch),
                                 media,
                                 status)


class PackageDetailsTask(TaskBase):
    """ Query for details of a package. """

    def __init__(self, bus, sender, worker, nvra):
        TaskBase.__init__(self, bus, sender, worker)
        self._id = (nvra[0], nvra[3])
        self._fullversion = (nvra[1], nvra[2])

    @dbus.service.signal(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                         signature='(ssss)sstt')
    def PackageDetails(self, nvra, group, summary, size, installtime):
        log.debug('PackageDetails signal emitted: %s', nvra)
        pass

    def worker_callback(self, urpmi, backend):
        try:
            for status in urpmi._cache[self._id].values():
                desc = status.get(self._fullversion)
                if desc:
                    pkg = desc['pkg']
                    installtime = desc.get('installtime', 0)
                    self.PackageDetails(pkg.nvra(),
                                        pkg.group,
                                        pkg.summary,
                                        pkg.size,
                                        installtime)
                    # Assuming that the are no more package versions
                    # in another status:
                    return
        except IndexError:
            self.Error('Unknow package (name, arch): %s' 
                       % self._id)
        self.Error('Unknow package version for %s: %s' 
                   % (self._id, self._fullversion))


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

    def worker_callback(self, urpmi, backend):
        for r in self._backend_helper(backend, 'search_files'):
            self.PackageFiles(r['name'], r['version'], r['release'],
                                  r['arch'], r['files'])
