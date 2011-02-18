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
## Author(s): Eugeni Dodonov <eugeni@mandriva.com>
##            J. Victor Martins <jvdm@mandriva.com>
##
##
""" URPMI repository manipulation. """

import os
import re
import gzip
import time
import subprocess


class Repo:
    """ Represents a synthesis hdlist parser. """

    _urpmi_cfg = "/etc/urpmi/urpmi.cfg"
    _media_synthesis = "/var/lib/urpmi/%s/synthesis.hdlist.cz"
    _list={}
    _path={}
    _operation_re=None
    _requires_re=None
    _name_installed="Installed"

    def __init__(self):
        self._requires_re=re.compile('^([^[]*)(?:\[\*\])*(\[.*])?')
        self._operation_re=re.compile('\[([<>=]*) *(.*)\]')
        self.medias = {}

    def find_medias(self):
        """Attempts to locate and configure available medias"""
        medias = {}
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
                medias[media] = (key, ignore, update)
        return medias

    def media_synthesis(self, media):
        """Returns media synthesis address"""
        return self._media_synthesis % media

    def split_requires(self,req_array):
        """split the requires in a dictionary"""
        res={}
        for i in req_array:
            require=self._requires_re.match(i)
            if require:
                name=require.groups()[0]
                res[name]={}
                condition=require.groups()[1]
                if condition:
                    op=''
                    version=''
                    o=self._operation_re.match(condition)
                    if o:
                        (op,version)=o.groups()[0:2]
                        res[name]['version']=version
                        res[name]['operation']=op
        return res

    def get_listpkgs(self):
        """ return the list of rpm parsed from the synthesis """
        return self._list

    def get_path(self,rpm):
        """ return the path of the rpm"""
        r=self._list[rpm]
        res= os.path.dirname(self._path[r['source']]['path'])+'/'
        res=res + self._path[r['source']]['rpm']+'/'
        return res+'/'+'%s-%s-%s.%s.rpm' % (rpm,r['version'],r['release'],r['arch'])

    def open_listing(self,f):
        """ open a local file synthesis """
        return gzip.open(f, "r")

    def add_hdlistpkgs(self,name_source,path,path_to_rpm='.'):
        """ add the synthesis.hdlist to the list """
        self._path[name_source]={}
        self._path[name_source]['path']=path
        self._path[name_source]['rpm']=path_to_rpm
        f=self.open_listing(path)
        tmp={}
        line=f.readline()
        while line:
            line=line.strip()
            l=line.split('@')[1:]
            if l[0] == 'summary':
                tmp['summary']=l[1]
            for i in ('requires','provides','conflict','obsoletes','suggests'):
                if l[0] == i:
                        tmp[i]=self.split_requires(l[1:])
            if l[0] == 'info':
                rpm=l[1].split('-')
                version=rpm[-2:-1][0]
                name='-'.join(rpm[0:-2])
                tmp['version']=version
                tmp['epoch']=l[2]
                tmp['size']=l[3]
                tmp['group']=l[4]
                tmp['source']=name_source
                tmp['release']='.'.join(rpm[-1].split('.')[0:-1])
                tmp['arch']=rpm[-1].split('.')[-1]
                tmp['installed']=None
                self._list[name]=tmp
                tmp={}
            line=f.readline()

    def add_installed(self):
        """Adds locally installed packages to the list"""
        fd = os.popen("rpm -qa --qf '%{name}|%{version}|%{epoch}|%{size}|%{group}|%{release}|%{arch}|%{installtime}|%{summary}\n'", "r")
        self._path[self._name_installed]={}
        self._path[self._name_installed]['path']=""
        self._path[self._name_installed]['rpm']=""
        for l in fd.readlines():
            name, version, epoch, size, group, release, arch, installed, summary = l.split("|")
            installed = time.ctime(int(installed))
            if name in self._list:
                self._list[name]['installed'] = installed
            else:
                self._list[name] = {'version': version,
                                'epoch': epoch,
                                'size': size,
                                'group': group,
                                'source': self._name_installed,
                                'release': release,
                                'summary': summary,
                                'arch': arch,
                                'installed': installed
                                }


    def uninstalled_deps(self, pkg_name):
        """Returns the list of uninstalled requires of a package pkg_name."""

        pkg = self._list[pkg_name]

        if pkg['installed'] != None:
            # All installed should have all it's requires installed, right?
            return []

        reqs = []
        if 'requires' in pkg:
            for r in pkg['requires']:
                if r not in self._list or not self._list[r]['installed']:
                    reqs.append(r)

        return reqs


    def install_pkg(self, pkg_name):
        """Calls urpmi to install a package."""

        urpmi = subprocess.Popen(['urpmi', '--force', '--quiet',
                                      '--download-all', pkg_name],
                                 stdout=subprocess.PIPE)
        ret = urpmi.wait()
        if (ret == 0):
            # sucessfully installed the package
            fd = os.popen("rpm -q %s --qf '%{installtime}'", "r")


    def uninstall_pkg(self, pkg_name):
        """Calls urpmi to uninstall pkg_name and all orphaned deps."""

        pkg = self._list[pkg_name]
