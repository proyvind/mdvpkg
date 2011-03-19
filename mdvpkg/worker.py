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
import subprocess
import threading
import Queue


WAIT_TASK_TIMEOUT = 6
gobject.threads_init()


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
            raise RuntimeError('backend already running')
        self.urpm = subprocess.Popen('',
                                     executable=self.path,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)
    def kill(self):
        if not self.urpm:
            raise RuntimeError("backend's not running")
        self.urpm.terminate()
        self.urpm = None

    def running(self):
        if self.urpm != None:
            return self.urpm.poll() == None
        return False
    
    def do(self, cmd, *args, **kwargs):
        """
        Send a command to the backend and return a list of results.

        Results are python objects, which were created from eval()'d
        string returned by the backend.
        """
        args_line = '\n'.join([ str(e) for e in args])
        if args_line:
            args_line += '\n'

        kwargs_line = '\n'.join([ '='.join([ str(e) for e in pair ])
                                 for pair in kwargs.items() ])
        if kwargs_line:
            kwargs_line += '\n'

        cmd_line = "%s\n%s%s\n" % (cmd, args_line, kwargs_line)
        self.urpm.stdin.write(cmd_line)

        while True:
            l = self.urpm.stdout.readline().strip()
            if not l:
                return
            if l == 'ERROR':
                raise BackendDoError(self.urpm.stdout.readline().strip())
            yield eval(l)


class TaskWorker(object):
    """ A worker for tasks.  Tasks are queued in order of addition. """
    
    def __init__(self, backend_path):
        self._queue = Queue.Queue()
        self._backend = Backend(backend_path)
        self._thread = threading.Thread(target=self._work_loop,
                                        name='mdvpkg-worker-thread')
        self._thread.start()

    def push(self, task):
        """ Add a task to the task queue. """
        self._queue.put(task, False)

    def stop(self):
        """ Signal the worker process to do the last task and quit. """
        self.__work = False

    def _work_loop(self):
        """ Worker's thread activity method. """
        self.__work = True
        while self.__work:
            try:
                task = self._queue.get()
                print 'Worker found task: %s, %s' % (task.path, task._sender)
                if not self._backend.running():
                    self._backend.run()
                task.worker_callback(self._backend)
                task.exit_callback()
            except Queue.Empty:
                if self._backend.running():
                    self._backend.kill()
