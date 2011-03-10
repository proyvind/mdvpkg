##
## Copyright (C) 2010-2011 Mandriva S.A <http://www.mandriva.com>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License along
## with this program; if not, write to the Free Software Foundation, Inc.,
## 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
##
##
## Author(s): J. Victor Martins <jvdm@mandriva.com>
##
""" Mandriva Package exceptions and errors. """


import dbus


class DaemonError(dbus.DBusException):
    """ Internal error in mdvpkg. """

    _dbus_error_name = "org.mandrivalinux.mdvpkg"


class UnknownTaskError(DaemonError):

    _dbus_error_name = "org.mandrivalinux.mdvpkg.UnknowTaskError"


class DifferentUserError(DaemonError):

    _dbus_error_name = "org.mandrivalinux.mdvpkg.DifferentUserError"
