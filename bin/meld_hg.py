#!/usr/bin/env python3

import sys
import os
from os.path import join, basename, splitext, dirname, abspath
import shutil
import tempfile
import re
import subprocess


# https://en.wikipedia.org/wiki/Comparison_of_programming_languages_(syntax)#Inline_comments
PYTHON_COMMENTS = set("""
sh bash py rb php r
""".split())
C_COMMENTS = set("""
c cpp cc h hpp cs d go java js kt rs scala swift
""".split())


HG_CONFLICT_RE = re.compile(r'''
^<<<<<<<.*?
(^.*?)
^\|\|\|\|\|\|\|.*?
^=======.*?
^>>>>>>>.*?
^''', re.MULTILINE | re.VERBOSE | re.DOTALL)


MYDIR = dirname(abspath(__file__))


def copy_sources(old_after, old_base, new_base, output):
    """
    Copy sources to other names which show their revision id and make meld
    syntax-highlight them.
    """
    tdir = tempfile.mkdtemp(prefix='meld')

    old_after_prefix = 'old-applied.'
    if 'HG_OTHER_NODE' in os.environ:
        old_after_prefix += os.environ['HG_OTHER_NODE'] + '.'
    old_after_dst = join(tdir, old_after_prefix + basename(output))
    shutil.copy2(old_after, old_after_dst)

    old_base_prefix = 'old-base.'
    if 'HG_BASE_NODE' in os.environ:
        old_base_prefix += os.environ['HG_BASE_NODE'] + '.'
    old_base_dst = join(tdir, old_base_prefix + basename(output))
    shutil.copy2(old_base, old_base_dst)

    new_base_prefix = 'new-base.'
    if 'HG_MY_NODE' in os.environ:
        new_base_prefix += os.environ['HG_MY_NODE'] + '.'
    new_base_dst = join(tdir, new_base_prefix + basename(output))
    shutil.copy2(new_base, new_base_dst)

    return old_after_dst, old_base_dst, new_base_dst


def change_conflict_markers(s, fn):
    _noext, dotext = splitext(fn)
    ext = dotext[1:]
    if ext in PYTHON_COMMENTS:
        prefix = "#"
    elif ext in C_COMMENTS:
        prefix = "//"
    else:
        prefix = ""

    repl = (r'{}<<<<<<<\n'
            r'\1'
            r'{}>>>>>>>\n'
            .format(prefix, prefix))
    return HG_CONFLICT_RE.sub(repl, s)


def meld_hg(old_after, old_base, new_base, output):
    old_after_dst, old_base_dst, new_base_dst = copy_sources(
        old_after, old_base, new_base, output)

    output_s = open(output).read()
    output_repl = change_conflict_markers(output_s, output)
    with open(output, 'w') as f:
        f.write(output_repl)

    meld_exe = join(MYDIR, 'meld')
    args = [meld_exe, old_after_dst, old_base_dst, new_base_dst, output]
    # I have seen TortoiseHG set PYTHONPATH to include python2.7 modules,
    # which interfered with python3. So I unset PYTHONPATH.
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    subprocess.call(args, env=env)

    output_r = open(output).read()
    is_conflicts_remaining = '<<<<<<<' in output_r or '>>>>>>>>' in output_r
    return 0 if not is_conflicts_remaining else 1


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('old_after', help='Old result after applying ($other)')
    parser.add_argument('old_base', help='Old base ($base)')
    parser.add_argument('new_base', help='New base ($local)')
    parser.add_argument('output',
                        help='destination in working directory ($output)')
    args = parser.parse_args()

    return meld_hg(args.old_after, args.old_base, args.new_base, args.output)


if __name__ == '__main__':
    sys.exit(main())
