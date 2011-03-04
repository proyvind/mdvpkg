import mdvpkgd
from distutils.core import setup
from glob import glob

data_files = [ ('/etc/dbus-1/system.d/',
                glob('dbus/*.conf')),
               ('/usr/share/dbus-1/system-services/',
                glob('dbus/*.service')) ]

setup(name='mdvpkgd',
      version=mdvpkgd.__version__,
      description='Mandriva Package Daemon',
      license='GNU GPLv3',
      author='J. Victor Martins',
      author_email='jvdm@mandriva.com',
      packages=['mdvpkgd'],
      scripts=['bin/mdvpkgd'],
      data_files=data_files)
