#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path
from shutil import copy, copytree
from subprocess import check_call
from tempfile import mkdtemp, mkstemp

mydir = Path(__file__).absolute().parent
repodir = mydir.parent


PREFIX_PATTERNS = [
    "bin/python",
    "bin/python3",
    "bin/python3.1",
    "bin/rsvg-convert",
    "include",
    "lib/cairo/libcairo-fdr.a",
    "lib/libpython*",
    "lib/python*/ensurepip",
    "share/doc",
    "share/locale",
    "share/man",
    "conda-meta",
]

SUFFIX_PATTERNS = [
    "__pycache__/*",
    "Makefile",
    "*.cmake",
    "valgrind/*",
    "*.a",
]

for dynmod in '_decimal _sha3 _ctypes _pickle _sqlite _ssl _curses _curses_panel'.split():
    PREFIX_PATTERNS.append(f'lib/python*/lib-dynload/{dynmod}.*')


APPDIR_EXEC_PREFIX = """\
#!/bin/sh
# The following line is executed by the shell and ignored by python.
'''exec' "$(dirname "$0")/python3.10" "$0" "$@" # '''

# Set environment variables for the relocatable installation
import os
from pathlib import Path
prefix = Path(__file__).resolve().parent.parent
os.environ['GI_TYPELIB_PATH'] = str(prefix / 'lib/girepository-1.0')
os.environ['XKB_CONFIG_ROOT'] = str(prefix / 'share/xkeyboard-config-2')
os.environ['FONTCONFIG_FILE'] = str(prefix / 'etc/fonts/fonts.conf')
os.environ['FONTCONFIG_PATH'] = str(prefix / 'etc/fonts')
"""


def sh(args: str) -> None:
    print(f"> {args}", file=sys.stderr)
    check_call(args, shell=True)


def create_venv(venvdir: Path) -> None:
    sh(f"{sys.executable} -m venv {venvdir}")
    sh(f"{venvdir}/bin/pip install build")


def build_wheel_and_targz(venvdir: Path, pypi_distdir: Path) -> None:
    sh(f"{venvdir}/bin/python -m build --outdir {pypi_distdir} {repodir}")


def update_recipe(recipe: str, targz: Path) -> str:
    sha256 = hashlib.sha256(targz.read_bytes()).hexdigest()
    lines = recipe.split('\n')
    url_i, = [i for i, line in enumerate(lines) if line.startswith('  url: ')]
    sha256_i, = [i for i, line in enumerate(lines) if line.startswith('  sha256: ')]
    lines[url_i] = f'  url: file://{targz}'
    lines[sha256_i] = f'  sha256: {sha256}'
    return '\n'.join(lines)


def build_conda_package(conda: Path, workdir: Path, targz: Path, conda_distdir: Path) -> None:
    recipe0 = mydir.joinpath('recipe.yaml').read_text()
    recipe = update_recipe(recipe0, targz)
    recipe_dir = workdir / 'recipe'
    recipe_dir.mkdir(exist_ok=True)
    recipe_fn = recipe_dir / 'recipe.yaml'
    recipe_fn.write_text(recipe)
    cbenv = workdir / 'cbenv'
    if not cbenv.exists():
        sh(f"{conda} create -y -p {cbenv} rattler-build binutils")
    sh(f"{cbenv}/bin/rattler-build build -r {recipe_fn} --output-dir {conda_distdir}")


def build_conda_env(conda: Path, conda_pkg_fn: Path, outenv: Path) -> None:
    sh(f"rm -rf {outenv}")
    sh(f"{conda} create -y -p {outenv}")
    sh(f"{conda} install -y -p {outenv} --no-deps python=3.10")
    sh(f"{conda} install -y -p {outenv} -c noamraph -c conda-forge gtk3 gtksourceview4 pygobject adwaita-icon-theme")
    sh(f"{conda} install -y -p {outenv} {conda_pkg_fn}")
    sh(f"{conda} remove -y -p {outenv} --force-remove libcups openssl ncurses krb5 libjpeg-turbo pcre2 bzip2")


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


def is_skip(rel: Path) -> bool:
    for pattern in PREFIX_PATTERNS:
        n_parts = len(pattern.split('/'))
        prefix = Path(*rel.parts[:n_parts])
        if prefix.match(pattern):
            return True
    for pattern in SUFFIX_PATTERNS:
        if rel.match(pattern):
            return True
    return False


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


def build_relocatable(strip: Path, src: Path, dst: Path):
    # This should be done in pytest, but currently it's the only test, so I just run it here.
    test_fix_solib_names()

    solib_groups = get_solib_groups(src)
    solib_re = get_solib_re(solib_groups)
    skip_solibs = set(name for names in solib_groups.values() for name in names[1:])

    for root0, _dirs, files in os.walk(src, topdown=False):
        root = Path(root0)
        relroot = root.relative_to(src)
        dstroot = dst.joinpath(relroot)
        made_dir = False
        for name in files:
            fn = root / name
            rel = relroot / name
            if name in skip_solibs or is_skip(rel) or (fn.is_symlink() and not fn.exists()):
                continue
            if not made_dir:
                dstroot.mkdir(exist_ok=True, parents=True)
                made_dir = True
            b = fix_solib_names(strip, solib_groups, solib_re, fn)
            if str(rel) == 'bin/meld-fourdiff':
                line0, rest = b.split(b'\n', 1)
                assert line0.startswith(b'#!')
                b = APPDIR_EXEC_PREFIX.encode('ascii') + rest
            dstfn = dstroot / name
            dstfn.write_bytes(b)
            dstfn.chmod(fn.stat().st_mode)


def get_my_version() -> str:
    s = repodir.joinpath('meson.build').read_text()
    match = re.search(r"version\s*:\s*'([^']+)'", s)
    assert match is not None
    return match.group(1)


def build_bundle_wheel(projdir: Path, venvdir: Path, appdir: Path, distdir: Path):
    version = get_my_version()
    projdir.mkdir()

    pyproject0 = mydir.joinpath('bundle-pyproject.toml').read_text()
    pyproject1 = pyproject0.replace('{VERSION}', version)
    assert pyproject1 != pyproject0
    pyproject = pyproject1.replace('{PLATFORM_TAG}', 'manylinux_2_28_x86_64')
    assert pyproject != pyproject1
    projdir.joinpath('pyproject.toml').write_text(pyproject)

    copy(repodir / 'README.md', projdir)
    copy(repodir / 'COPYING', projdir)
    copy(mydir / 'hatch_force_platform_tag.py', projdir)

    pkgdir = projdir / 'meld_bundle'
    pkgdir.mkdir()
    copy(mydir / 'bundle_shim.py', pkgdir / '__init__.py')

    copytree(appdir, pkgdir / 'appdir', symlinks=True)

    sh(f"{venvdir}/bin/python -m build --outdir {distdir} --wheel {projdir}")


def build_all(conda: Path, workdir: Path):
    venvdir = workdir / 'venv'
    if not venvdir.exists():
        create_venv(venvdir)

    pypi_distdir = workdir / 'dist'
    if not pypi_distdir.exists():
        build_wheel_and_targz(venvdir, pypi_distdir)
    _wheel, = pypi_distdir.glob("*.whl")
    targz, = pypi_distdir.glob("*.tar.gz")

    conda_distdir = workdir / 'cdist'
    if not conda_distdir.exists():
        build_conda_package(conda, workdir, targz, conda_distdir)
    cbenv = workdir / 'cbenv'
    conda_pkg_fn, = conda_distdir.glob("noarch/*.conda")

    outenv = workdir / 'outenv'
    if not outenv.exists():
        build_conda_env(conda, conda_pkg_fn, outenv)

    appdir = workdir / 'appdir'
    strip = cbenv / 'bin/strip'
    assert strip.exists()
    if not appdir.exists():
        build_relocatable(strip, outenv, appdir)

    projdir = workdir / 'meld-fourdiff-bundle'
    bundle_distdir = workdir / 'bundle-dist'
    build_bundle_wheel(projdir, venvdir, appdir, bundle_distdir)


def main():
    from argparse import ArgumentParser

    parser = ArgumentParser(description="build and bundle")
    parser.add_argument("--workdir", type=Path, help="Path for work. If not given, will be chosen in /tmp")
    parser.add_argument("conda", type=Path, help="path to conda executable")
    args = parser.parse_args()

    workdir = args.workdir or Path(mkdtemp(prefix="meld-bundler-workdir-"))
    build_all(args.conda, workdir)


if __name__ == "__main__":
    main()
