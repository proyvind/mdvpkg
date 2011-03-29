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


import signal
import time
import logging
import gobject
import subprocess
import threading
import collections

import mdvpkg.repo


WAIT_TASK_TIMEOUT = 15
gobject.threads_init()

log_backend = logging.getLogger('mdvpkgd.backend')
log = logging.getLogger('mdvpkgd.worker')


class BackendError(Exception):
    """Base class for backend exceptions."""
    pass


class BackendDoError(BackendError):
    """Raised when backend terminated a command in error."""
    pass


class Backend(object):
    """ Represents the running urpm backend. """

    def __init__(self, path):
        self.path = path
        self.urpm = None

    def run(self):
        if self.urpm:
            log_backend.error("run() called and backend's already running.")
            return
        self.urpm = subprocess.Popen('',
                                     executable=self.path,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)
        log_backend.debug('Backend started')

    def kill(self):
        if not self.urpm:
            log_backend.error("kill() called and backend's running.")
            return
        self.urpm.send_signal(signal.SIGTERM)
        # wait for child to terminate
        self.urpm.communicate()
        self.urpm = None
        log_backend.debug('Backend killed')

    def running(self):
        if self.urpm != None:
            return self.urpm.poll() == None
        return False
    
    def do(self, cmd, *args, **kwargs):
        """
        Send a command to the backend and return a response generator.
        """

        # Generating command for the backend ...

        args_line = '\n'.join([ str(e) for e in args])
        if args_line:
            args_line += '\n'

        kwargs_line = '\n'.join([ '='.join([ str(e) for e in pair ])
                                 for pair in kwargs.items() ])
        if kwargs_line:
            kwargs_line += '\n'

        cmd_line = "%s\n%s%s\n" % (cmd, args_line, kwargs_line)
        self.urpm.stdin.write(cmd_line)

        # Response loop ...

        while True:
            resp = self.urpm.stdout.readline()

            # Incomplete line, means the pipe was closed before a
            # whole response was received from backend:
            if not resp or not resp.endswith('\n'):
                if self.running():
                    self.kill()
                    raise BackendDoError(
                        "Backend's communication pipe closed, killing."
                        )
                else:
                    raise BackendDoError('Backend died unexpectedly.')

            (tag, data) = self._parse_response(resp)

            # ERROR and END will stop the response generation ...

            if tag == 'ERROR':
                raise BackendDoError(data)                
            elif tag == 'END':
                break
            elif tag == 'LOG':
                log_backend.debug(data)
            elif tag == 'RESULT':
                yield eval(data)
            else:
                raise BackendDoError('Unknown response: %s' % resp)
            
    def _parse_response(self, l):
        i = l.find(' ')
        return l[:i], l[i+1:].strip()


class TaskWorker(object):
    """ A worker for tasks.  Tasks are queued in order of addition. """
    
    def __init__(self, backend_path):
        self._queue = collections.OrderedDict()
        self._backend = Backend(backend_path)
        self._thread = threading.Thread(target=self._work_loop,
                                        name='mdvpkg-worker-thread')
        self._new_task = threading.Event()
        self._queue_lock = threading.Lock()
        self._thread.daemon = True
        log.debug('Loading urpmi db')
        self.urpmi = mdvpkg.repo.URPMI()
        self.urpmi.load_db()
        log.debug('urpmi db loaded')
        self._thread.start()
        self._task = None
        self._last_action_timestamp = time.time()
        self._backend.run()


    def push(self, task):
        """ Add a task to the task queue. """
        with self._queue_lock:
            self._queue[task.path] = task
        self._new_task.set()

    def inactive(self, idle_timeout):
        return time.time() - self._last_action_timestamp > idle_timeout \
                   and len(self._queue) == 0 \
                   and not self._task

    def stop(self):
        """ Signal the worker process to do the last task and quit. """
        self.__work = False
        self._new_task.set()
        self._thread.join()

    def cancel(self, task):
        if self._task == task:
            # TODO Currently the task won't be cancelled, should we
            #      put a flag in the for cancellation request?
            return
        else:
            # Not running the task, so we remove it from the queue.
            # It's an error if the task was not queued ...
            with self._queue_lock:
                t = self._queue.pop(task.path, None)
                if not t:
                    log.error('Cancelling not queued task')
                if t != task:
                    log.error('Cancelling a task with different path')

    def _work_loop(self):
        """ Worker's thread activity method. """
        log.info("Thread initialized")
        self.__work = True
        while self.__work:
            try:
                with self._queue_lock:
                    (path, self._task) = self._queue.popitem(last=False)
            except KeyError:
                if not self._new_task.wait(WAIT_TASK_TIMEOUT) \
                       and self._backend.running():
                    log.info('No tasks available, Killing backend')
                    self._backend.kill()
            else:
                self._new_task.clear()
                try:
                    self._last_action_timestamp = time.time()
                    log.debug('Got a task: %s', self._task.path)
                    if not self._backend.running():
                        self._backend.run()
                    self._task.worker_callback(self.urpmi, self._backend)
                    self._task.exit_callback()
                    self._task = None
                except Exception as e:
                    log.exception("Raised in worker's thread")

        if self._backend.running():
            self._backend.kill()
        log.info("Worker's thread killed")
