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
## Author(s): Eugeni Dodonov <eugeni@mandriva.com>
##            J. Victor Martins <jvdm@mandriva.com>
##
""" URPMI repository manipulation. """


import re
import gzip
import collections
import subprocess

import mdvpkg.rpmutils


class Media:
    """ Represents a URPMI media. """

    _hdlist_path_tpl = "/var/lib/urpmi/%s/synthesis.hdlist.cz"

    def __init__(self, name, update, ignore, key='', compressed=True):
        self.name = name
        self.ignore = ignore
        self.update = update
        self.key = key
        if compressed:
            import gzip
            self._open = gzip.open
        else:
            self._open = open
        self._hdlist_path = self._hdlist_path_tpl % name
        # name-version-release[disttagdistepoch].arch regexp:

        # FIXME This is a ugly hack.  Some packages comes with
        #       disttag/distepoch in their file names, separated by
        #       '-'.  And synthesis provides NVRA information in the
        #       rpm file name.  So we check if <release> starts with
        #       'm' for 'mdv' (our currently disttag).

        self._nvra_re = re.compile('^(?P<name>.+)-'
                                   '(?P<version>[^-]+)-'
                                   '(?P<release>[^m].*)\.'
                                   '(?P<arch>.+)$')
        self._cap_re = re.compile('^(?P<name>[^[]+)'
                                  '(?:\[\*])*(?:\[(?P<cond>[<>=]*)'
                                  ' *(?P<ver>.*)])?')

    def list(self):
        """
        Open the hdlist file and yields package data in it.
        """
        with self._open(self._hdlist_path, 'r') as hdlist:
            pkg = {}
            for line in hdlist:
                fields = line.rstrip('\n').split('@')[1:]
                tag = fields[0]
                if tag == 'info':
                    (pkg['name'],
                     pkg['version'],
                     pkg['release'],
                     pkg['arch']) = self.parse_rpm_name(fields[1])
                    for (i, field) in enumerate(('epoch', 'size', 'group')):
                        pkg[field] = fields[2 + i]
                    yield pkg
                    pkg = {}
                elif tag == 'summary':
                    pkg['summary'] = fields[1]
                elif tag in ('requires', 'provides', 'conflict',
                                   'obsoletes'):
                    pkg[tag] = self._parse_capability_list(fields[1:])

    def parse_rpm_name(self, name):
        """
        Returns (name, version, release, arch) tuple from a rpm
        package name.  Handle both names with and without
        {release}-{disttag}{distepoch}.
        """
        m = self._nvra_re.match(name)
        if not m:
            raise ValueError, 'Malformed RPM name: %s' % name

        release = m.group('release')
        if release.find('-') != -1:
            release = release.split('-')[0]

        return (m.group('name'),
                m.group('version'),
                release,
                m.group('arch'))

    def _parse_capability_list(self, cap_str_list):
        """
        Parse a list of capabilities specification string from hdlist
        files together with their restrictions.  Returns a list of
        dictionaries for each capability.
        """
        cap_list = []
        for cap_str in cap_str_list:
            m = self._cap_re.match(cap_str)
            if m is None:
                continue    # ignore malformed names
            cap_list.append({ 'name': m.group('name'),
                              'condition': m.group('cond'),
                              'version': m.group('ver') })
        return tuple(cap_list)


class RpmPackage(object):
    """ Represents a RPM package. """

    def __init__(self, name, version, release, arch, epoch,
                     size, group, summary, requires=[], provides=[],
                     conflict=[], obsoletes=[]):
        self.name = name
        self.version = version
        self.release = release
        self.arch = arch
        self.epoch = epoch
        self.size = size
        self.group = group
        self.summary = summary
        self.requires = requires
        self.provides = provides
        self.conflict = conflict
        self.obsoletes = obsoletes

    def na(self):
        """
        Package Name-Arch: identifies uniquely the software packaged.
        """
        return (self.name, self.arch)

    def evr(self):
        """
        Package Epoch-Version-Release: identifies a specific package
        version.
        """
        return (self.epoch, self.version, self.release)

    def nvra(self):
        """
        Package Name-Version-Release-Arch: identifies uniquely the
        package.
        """
        return (self.name, self.version, self.release, self.arch)

    def __eq__(self, other):
        return self.nvra() == other.nvra()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __le__(self, other):
        if self == other:
            return True
        else:
            return NotImplemented

    def __ge__(self, other):
        return self.__le__(other)

    def __cmp__(self, other):
        if self.na() != other.na():
            raise ValueError('Name-arch mismatch %s != %s'
                             % (self.na(), other.na()))
        if self.epoch > other.epoch:
            return 1;
        elif self.epoch < other.epoch:
            return -1;
        cmp = mdvpkg.rpmutils.rpmvercmp(self.version, other.version)
        if cmp == 0:
            cmp = mdvpkg.rpmutils.rpmvercmp(self.release, other.release)
        return cmp

    def __str__(self):
        return '%s-%s-%s.%s' % self.nvra()

    def __repr__(self):
        return '%s(%s:%s)' % (self.__class__.__name__,
                              self,
                              self.epoch)


class URPMI(object):
    """ Represents a urpmi database. """

    _urpmi_cfg = "/etc/urpmi/urpmi.cfg"

    def __init__(self):
        self._medias = None
        self._cache = {}

    @property
    def medias(self):
        """
        Get the list of package medias in the repo.  Late
        initialization is used.
        """
        if not self._medias:
            self._load_medias()
        return self._medias

    @medias.deleter
    def medias(self):
        self._medias = None


    @property
    def packages(self):
        if not self._cache:
            self.load_db()

    def search_name(self, n):
        result = []
        for name, arch in self._cache:
            if n == name:
                result.append((name, arch))
        return result

    def load_db(self):
        self._cache = {}
        self._load_installed()
        for media in [m for m in self.medias.values() if not m.ignore]:
            for pkg_data in media.list():
                pkg = RpmPackage(**pkg_data)
                self._load_pkg_from_media(pkg, media.name)

    def _load_installed(self):
        """ Populate installed cache with package in local rpm db. """
        rpm = subprocess.Popen("rpm -qa --qf '%{NAME}@%{VERSION}@%{RELEASE}"
                                   "@%{ARCH}@%|EPOCH?{%{EPOCH}}:{0}|"
                                   "@%{SIZE}@%{GROUP}@%{SUMMARY}"
                                   "@%{INSTALLTIME}\n'",
                               stdout=subprocess.PIPE,
                               stdin=None,
                               shell=True)
        for line in rpm.stdout:
            fields = line.split('@')
            pkg = RpmPackage(*fields[:-1])
            installtime = int(fields[-1])

            name = pkg.na()
            entry = self._get_or_create_cache_entry(name)
            version = pkg.evr()

            assert version not in entry['current'], \
                'installed pkg with same version: %s' % pkg
            desc = self._create_pkg_desc(pkg,
                                         installtime=installtime)
            entry['current'][version] = desc
        rpm.wait()

    def _load_pkg_from_media(self, pkg, media_name):
        name = pkg.na()
        version = pkg.evr()
        entry = self._get_or_create_cache_entry(name)
        if entry['current']:
            current = entry['current']
            if version in current:
                current[version]['media'] = media_name
            else:
                desc = self._create_pkg_desc(pkg, media_name)
                installed_pkgs = [v['pkg'] for v in current.values()]
                recent_pkg = sorted(installed_pkgs)[-1]
                if pkg > recent_pkg:
                    entry['upgrade'][version] = desc
                else:
                    entry['downgrade'][version] = desc
        else:
            entry['new'][version] = self._create_pkg_desc(pkg, media_name)

    def _get_or_create_cache_entry(self, name):
        if name not in self._cache:
            entry = {'upgrade': {},
                     'downgrade': {},
                     'current': {},
                     'new': {}}
            self._cache[name] = entry
        else:
            entry = self._cache[name]
        return entry

    def _create_pkg_desc(self, pkg, media='', installtime=None):
        desc = {'pkg': pkg, 'media': media}
        if installtime:
            desc['installtime'] = installtime
        return desc

    def _load_medias(self):
        """
        Locate all configured medias.
        """
        self._medias = {}
        media_r = re.compile('^(.*) {([\s\S]*?)\s*}', re.MULTILINE)
        ignore_r = re.compile('.*(ignore).*')
        update_r = re.compile('.*(update).*')
        key_r = re.compile('.*key-ids:\s* (.*).*')
        url_r = re.compile('(.*) (.*://.*|/.*$)')
        with open(self._urpmi_cfg, "r") as fd:
            data = fd.read()
            res = media_r.findall(data)
            for media, values in res:
                res2 = url_r.findall(media)
                if res2:
                    # found a media with url, fixing
                    name, url = res2[0]
                    media = name
                media = media.replace('\\', '')
                media = media.strip()
                key = ""
                ignore=False
                update=False
                keys = key_r.findall(values)
                if keys:
                    key = keys[0]
                if ignore_r.search(values):
                    ignore=True
                if update_r.search(values):
                    update=True
                self._medias[media] = Media(media, update, ignore, key)
