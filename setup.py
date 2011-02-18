from distutils.core import setup
from glob import glob

data_files = [('/etc/dbus-1/system.d/', glob('dbus/*.conf')),
              ('/usr/share/dbus-1/system-services/', glob('dbus/*.service'))]

setup(name='mdvpkgd',
      version='0.1.0',
      description='Mandriva Package Daemon',
      author='J. Victor Martins',
      author_email='jvdm@mandriva.com',
      packages=['mdvpkgd'],
      data_files=data_files
     )
