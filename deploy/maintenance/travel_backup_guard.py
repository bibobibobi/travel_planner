#!/usr/bin/python3
"""Root-owned fixed-path metadata guard. Never imports or runs release code."""
import json
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path('/opt/travel-app')
STATE = ROOT / 'deployment-state/deployment-state.json'
CURRENT = ROOT / 'current'
SHA = re.compile(r'[0-9a-f]{40}\Z')
MAX_STATE = 65536
MAX_PACKAGES = 2 * 1024 * 1024


class GuardError(ValueError):
    pass


def trusted(path, *, directory=False, root_only=False):
    for part in (path, *path.parents):
        info = part.lstat()
        is_dir = part != path or directory
        if not (stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode)):
            raise GuardError('unsafe file type or ancestor')
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise GuardError('untrusted ownership or permissions')
        if not is_dir and info.st_nlink != 1:
            raise GuardError('hardlinked file')
    if root_only and path.stat().st_mode & 0o077:
        raise GuardError('state is not root-only')


def read_file(path, limit, *, root_only=False):
    trusted(path, root_only=root_only)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or
                info.st_mode & (0o077 if root_only else 0o022)):
            raise GuardError('unsafe opened file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if not data or len(data) > limit:
            raise GuardError('invalid file size')
        return data
    finally:
        os.close(fd)


def healthy_release():
    trusted(ROOT, directory=True)
    trusted(STATE.parent, directory=True, root_only=True)
    state = json.loads(read_file(STATE, MAX_STATE, root_only=True))
    if (not isinstance(state, dict) or set(state) != {'current', 'previous', 'transaction'} or
            not isinstance(state['current'], str) or not SHA.fullmatch(state['current']) or
            state['transaction'] is not None or
            (state['previous'] is not None and
             (not isinstance(state['previous'], str) or not SHA.fullmatch(state['previous'])))):
        raise GuardError('deployment state is pending or invalid')
    info = CURRENT.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise GuardError('unsafe current link')
    release = CURRENT.resolve(strict=True)
    if release != ROOT / 'releases' / state['current']:
        raise GuardError('current does not match healthy state')
    if read_file(release / 'REVISION', 128) != (state['current'] + '\n').encode('ascii'):
        raise GuardError('revision mismatch')
    return release


def current_packages():
    release = healthy_release()
    data = read_file(release / 'venv/BUILD-PACKAGES.txt', MAX_PACKAGES)
    text = data.decode('utf-8')
    if '\x00' in text or not all('==' in line and line.strip() == line for line in text.splitlines()):
        raise GuardError('invalid package list')
    return data


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ('verify-state', 'packages'):
        print('ERROR: invalid backup guard invocation', file=sys.stderr)
        return 1
    try:
        packages = current_packages()
        if sys.argv[1] == 'packages':
            sys.stdout.buffer.write(packages)
    except (GuardError, OSError, ValueError, UnicodeError) as error:
        print(f'ERROR: backup guard rejected input: {type(error).__name__}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
