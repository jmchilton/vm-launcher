# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Structure of this file is largely drived from setup.py of libcloud project
# which can be found at http://libcloud.apache.org/
from distutils.core import setup
from distutils.core import Command

from subprocess import call
from os import getcwd
import sys

if sys.version_info <= (2, 5):
    version = '.'.join([str(x) for x in sys.version_info[:3]])
    print('Version %s is not supported.  Please use Python 2.6' % version)
    sys.exit(1)


class Pep8Command(Command):
    description = "run pep8 script"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            import pep8
            pep8
        except ImportError:
            print ('Missing "pep8" library. You can install it using pip: '
                  'pip install pep8')
            sys.exit(1)

        cwd = getcwd()
        retcode = call(('pep8 %s/vmlauncher/ %s/test/' % (cwd, cwd)).split(' '))
        sys.exit(retcode)

setup(
    name='vm-launcher',
    version='0.1',
    description='A python library for seemlessly connecting libcloud and vagrant and fabric.',
    author='John Chilton',
    author_email='jmchilton@gmail.com',
    packages=[
        'vmlauncher'
    ],
    package_dir={
        'vmlauncher': 'vmlauncher',
    },
    license='Apache License (2.0)',
    url='https://github.com/jmchilton/vm-launcher/',
    cmdclass={
        'pep8': Pep8Command,
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.0',
        'Programming Language :: Python :: 3.1',
        'Programming Language :: Python :: 3.2',
        'Programming Language :: Python :: Implementation :: PyPy'])
