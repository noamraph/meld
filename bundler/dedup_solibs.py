from __future__ import annotations

import os
import re
from pathlib import Path
from subprocess import check_call
from tempfile import mkstemp


def get_solib_groups(env: Path) -> dict[str, list[str]]:
    libdir = env / 'lib'
    solib_groups: dict[str, list[str]] = {}
    for fn in libdir.iterdir():
        name = fn.name
        if '.so' not in name:
            continue
        base = name[:name.index('.so') + 3]
        if base == 'libgcc_s.so':
            # This is special, libgcc_s.so and libgcc_s.so.1 are different
            continue
        solib_groups.setdefault(base, []).append(name)
    for names in solib_groups.values():
        # Sort fns so the first one is the shortest one, which should be copied
        names.sort(key=lambda name: len(name))
        fns = [libdir.joinpath(name) for name in names]
        # In some cases there are equal files which are not symlinks. So just read all of them.
        bs = [fn.read_bytes() for fn in fns]
        for fn, b in zip(fns, bs):
            if b != bs[0]:
                raise RuntimeError(f"Expecting {fns[0]} and {fn} to have the same content")
    return solib_groups


def fix_solib_names_in_bytes(solib_groups: dict[str, list[str]], solib_re: re.Pattern[bytes], matches: list[re.Match[bytes]], b0: bytes, is_binary: bool) -> bytes:
    if is_binary:
        terminators = [0]
    else:
        terminators = [ord(','), ord('"')]
    b = bytes()
    last_pos = 0
    ignore_matches_before = 0
    for match in matches:
        if match.start() < ignore_matches_before:
            continue
        short = match.group(0)
        names = solib_groups[short.decode('ascii')]
        for end_pos in range(match.start(), len(b0)):
            if b0[end_pos] in terminators:
                break
        else:
            # We accept the end of string as a terminator, for the recursive call.
            end_pos = len(b0)
        segment = b0[match.start():end_pos]
        name = segment.decode('ascii')
        if name not in names:
            if name == 'libGLX.so.1':
                # Probably refers to the OS
                continue
            if is_binary:
                # We can have a string like "libharfbuzz-gobject.so.0,libharfbuzz.so.0" in a binary typelib file.
                # So we call ourselves with is_binary=False, to try to replace it with a shorter string.
                matches2 = list(solib_re.finditer(segment))
                short = fix_solib_names_in_bytes(solib_groups, solib_re, matches2, segment, is_binary=False)
                ignore_matches_before = end_pos
            else:
                raise RuntimeError(f"Found string {name} but it's not in {names}")

        b += b0[last_pos:match.start()]
        b += short
        if is_binary:
            b += b'\0' * (len(segment) - len(short))
        # Note that the terminator will be copied on the next iteration
        last_pos = end_pos
    b += b0[last_pos:]
    return b


def fix_solib_names(strip: Path, solib_groups: dict[str, list[str]], solib_re: re.Pattern[bytes], fn: Path) -> bytes:
    b0 = fn.read_bytes()
    if b0[:4] == b'\x7fELF':
        fd, path = mkstemp()
        try:
            os.close(fd)
            check_call([strip, fn, '-o', path], text=False)
            b0 = Path(path).read_bytes()
        finally:
            os.remove(path)
    matches = list(solib_re.finditer(b0))
    if not matches:
        return b0
    magic = b0[:4]
    if magic in (b'\x7fELF', b'GOBJ'):
        is_binary = True
    elif magic == b'<?xm':
        is_binary = False
    else:
        raise RuntimeError(f"File {fn} contains the name of a solib at position {matches[0].start()} but is not of a supported format")
    return fix_solib_names_in_bytes(solib_groups, solib_re, matches, b0, is_binary)


def get_solib_re(solib_groups: dict[str, list[str]]) -> re.Pattern[bytes]:
    return re.compile(b'|'.join(re.escape(name.encode('ascii')) for name in solib_groups.keys()))


def test_fix_solib_names():
    solib_groups = {
        'libharfbuzz-gobject.so': ['libharfbuzz-gobject.so', 'libharfbuzz-gobject.so.0'],
        'libharfbuzz.so': ['libharfbuzz.so', 'libharfbuzz.so.0'],
    }
    solib_re = get_solib_re(solib_groups)
    b0 = b"GOBJ\1\2\3libharfbuzz-gobject.so.0,libbla,libharfbuzz.so.0\0FOO"
    fd, fn = mkstemp()
    try:
        os.write(fd, b0)
        os.close(fd)
        b1 = fix_solib_names(Path('/dev/null'), solib_groups, solib_re, Path(fn))
    finally:
        os.remove(fn)
    assert b1 == b"GOBJ\1\2\3libharfbuzz-gobject.so,libbla,libharfbuzz.so\0\0\0\0\0FOO"
