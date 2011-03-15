#!/usr/bin/python

import sys
import dbus
import mdvpkg
import gobject
from dbus.mainloop.glib import DBusGMainLoop

try:
    task_name = sys.argv[1]
except IndexError:
    print 'Missing task name.'
    sys.exit(1)

print 'TASK:', task_name, sys.argv[2:]
DBusGMainLoop(set_as_default=True)
loop = gobject.MainLoop()

bus = dbus.SystemBus()

def signal_cb(*args, **kwargs):
    signal = kwargs['signal']
    print 'SIGNAL %s: %s' % (signal, args)
    if signal == 'Finished':
        loop.quit()

bus.add_signal_receiver(signal_cb, dbus_interface=mdvpkg.DBUS_INTERFACE,
                        member_keyword='signal')
bus.add_signal_receiver(signal_cb, dbus_interface=mdvpkg.DBUS_TASK_INTERFACE,
                        member_keyword='signal')

proxy = bus.get_object(mdvpkg.DBUS_SERVICE, mdvpkg.DBUS_PATH)
task_path = getattr(proxy, task_name)(dbus_interface=mdvpkg.DBUS_INTERFACE,
                                      *sys.argv[2:])

task_proxy = bus.get_object(mdvpkg.DBUS_SERVICE, task_path)
task_proxy.Run(dbus_interface=mdvpkg.DBUS_TASK_INTERFACE)

loop.run()
