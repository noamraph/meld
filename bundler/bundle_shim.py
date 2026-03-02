#!/usr/bin/env python3

import subprocess
import sys
from os.path import dirname, join


def main():
    exe = join(dirname(__file__), 'appdir/bin/meld-fourdiff')
    rc = subprocess.call([exe] + sys.argv[1:])
    sys.exit(rc)

if __name__ == '__main__':
    main()
