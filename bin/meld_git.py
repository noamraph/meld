#!/usr/bin/env python3

import sys
from os.path import join, dirname, abspath, exists
import subprocess


def main():
    from argparse import ArgumentParser

    parser = ArgumentParser(description='Run fourdiff meld with the correct argument order')
    parser.add_argument('remote')
    parser.add_argument('base')
    parser.add_argument('local')
    parser.add_argument('merged')
    args = parser.parse_args()

    meld_exe = join(dirname(abspath(__file__)), 'meld')
    # This seems to work to determine whether we're in a rebase.
    # Based on https://stackoverflow.com/a/67245016/343036
    is_rebase = exists('.git/rebase-apply') or exists('.git/rebase-merge')
    if is_rebase:
        # For some reason, in 'git rebase', LOCAL and REMOTE are swapped.
        args.remote, args.local = args.local, args.remote
    return subprocess.call([meld_exe, args.remote, args.base, args.local, args.merged])


if __name__ == '__main__':
    sys.exit(main())
