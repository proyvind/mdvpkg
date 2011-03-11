import mdvpkg
from distutils.core import setup
from glob import glob

data_files = [ ('/etc/dbus-1/system.d/',
                glob('dbus/*.conf')),
               ('/usr/share/dbus-1/system-services/',
                glob('dbus/*.service')),
               (mdvpkg.DEFAULT_BACKEND_DIR,
                glob('backend/*')),
               ('/usr/sbin/',
                ['bin/mdvpkgd']) ]

setup(name='mdvpkg',
      version=mdvpkg.__version__,
      description='Mandriva Package Daemon',
      license='GNU GPL',
      author='J. Victor Martins',
      author_email='jvdm@mandriva.com',
      packages=['mdvpkg'],
      data_files=data_files)
