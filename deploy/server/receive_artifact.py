#!/usr/bin/python3
"""Receive and validate an artifact; this program never deploys a release.

Install alongside artifact_stream.py as root-owned files. The only input is a
single ASCII revision/digest header followed by binary data on stdin.
"""
import fcntl
import grp
import hashlib
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from artifact_stream import DIGEST, MAX_BYTES, REVISION, ReceiveError, receive

ROOT = Path('/opt/travel-app')
CONFIG = Path('/etc/travel-deploy')
SNAPSHOTS = ROOT / 'artifact-snapshots'
LOCK = ROOT / '.lifecycle.lock'
VALIDATOR = ROOT / 'tools/validate_artifact.py'
VALIDATOR_USER = 'travel-build'
LIMITS = {'incoming': 100 * 1024**2, 'staging': 300 * 1024**2,
          'build-inputs': 100 * 1024**2, 'artifact-snapshots': 200 * 1024**2}
MIN_FREE = 512 * 1024**2


class Rejected(Exception):
    pass


def trusted(path, directory=False):
    """Reject mutable or linked components of a root-controlled path."""
    for part in (path, *path.parents):
        info = part.lstat()
        expected_dir = part != path or directory
        if not (stat.S_ISDIR(info.st_mode) if expected_dir else stat.S_ISREG(info.st_mode)):
            raise Rejected('unsafe trusted path')
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise Rejected('unsafe trusted path permissions')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise Rejected('unsafe trusted file links')


def authorization(revision, digest):
    mode_file = CONFIG / 'mode'
    trusted(CONFIG, directory=True)
    if CONFIG.stat().st_mode & 0o077:
        raise Rejected('authorization directory must be root-only')
    if mode_file.exists():
        trusted(mode_file)
        if mode_file.stat().st_mode & 0o077:
            raise Rejected('authorization mode must be root-only')
        mode = mode_file.read_text(encoding='ascii').strip()
    else:
        mode = 'manual'
    if mode == 'manual':
        allow = CONFIG / 'allowed-artifacts'
        trusted(allow)
        if allow.stat().st_mode & 0o077:
            raise Rejected('allowlist must be root-only')
        if f'{revision} {digest}' not in allow.read_text(encoding='ascii').splitlines():
            raise Rejected('artifact not authorized')
    elif mode != 'trusted-ci':
        raise Rejected('invalid authorization mode')


def usage(path):
    """Conservatively count entries without following symlinks or special files."""
    total = 0
    count = 0
    def walk(fd, depth=0):
        nonlocal total, count
        if depth > 32:
            raise Rejected('capacity tree too deep')
        for name in os.listdir(fd):
            count += 1
            if count > 100000:
                raise Rejected('capacity tree contains too many entries')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    walk(child, depth + 1)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
            else:
                raise Rejected('unsafe entry in capacity accounting')
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(fd)
    finally:
        os.close(fd)
    return total


def capacity():
    for name, limit in LIMITS.items():
        path = ROOT / name
        if not path.is_dir() or path.is_symlink() or usage(path) + MAX_BYTES > limit:
            raise Rejected('capacity limit exceeded')
    if shutil.disk_usage(ROOT).free < MIN_FREE + MAX_BYTES:
        raise Rejected('insufficient disk space')


def take_lock(timeout=30):
    trusted(LOCK)
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise Rejected('lifecycle lock timeout')
            time.sleep(0.1)


def reuse_lock(fd):
    """Validate and acquire the caller's descriptor without replacing it."""
    trusted(LOCK)
    expected = LOCK.stat()
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
        raise Rejected('invalid lifecycle lock descriptor')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise Rejected('lifecycle lock is not available') from error


def read_header(fd):
    # Header is produced by the fixed wrapper; do not buffer artifact bytes.
    import select
    deadline = time.monotonic() + 120
    header = bytearray()
    while len(header) <= 105:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise Rejected('header timeout')
        byte = os.read(fd, 1)
        if byte == b'\n':
            break
        if not byte:
            raise Rejected('missing header')
        header.extend(byte)
    if not re.fullmatch(rb'[0-9a-f]{40} [0-9a-f]{64}', header):
        raise Rejected('invalid header')
    return header.decode('ascii').split(' ')


def accept(fd, *, lifecycle_fd=None, allow_existing=False):
    revision, digest = read_header(fd)
    if not REVISION.fullmatch(revision) or not DIGEST.fullmatch(digest):
        raise Rejected('invalid parameters')
    trusted(SNAPSHOTS, directory=True)
    trusted(VALIDATOR)
    account = pwd.getpwnam(VALIDATOR_USER)
    deploy = pwd.getpwnam('travel-deploy')
    build_group = grp.getgrgid(account.pw_gid)
    info = SNAPSHOTS.stat()
    if (stat.S_IMODE(info.st_mode) != 0o710 or info.st_gid != account.pw_gid
            or deploy.pw_gid == account.pw_gid or deploy.pw_name in build_group.gr_mem
            or account.pw_uid == deploy.pw_uid or account.pw_uid == 0):
        raise Rejected('unsafe validator or snapshot permissions')
    authorization(revision, digest)
    lock = take_lock() if lifecycle_fd is None else lifecycle_fd
    if lifecycle_fd is not None:
        reuse_lock(lock)
    temp = None
    try:
        capacity()
        final = SNAPSHOTS / (revision + '-' + digest + '.tar.gz')
        if os.path.lexists(final) and not allow_existing:
            raise Rejected('snapshot already exists')
        handle, temp = tempfile.mkstemp(prefix='.incoming-', dir=SNAPSHOTS)
        with os.fdopen(handle, 'w+b') as stream:
            size = receive(fd, stream, revision, digest)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            actual = hashlib.sha256()
            for block in iter(lambda: stream.read(65536), b''):
                actual.update(block)
            if actual.hexdigest() != digest:
                raise Rejected('snapshot digest mismatch')
        os.chown(temp, 0, account.pw_gid)
        os.chmod(temp, 0o440)
        subprocess.run(['/usr/sbin/runuser', '-u', VALIDATOR_USER, '--', '/usr/bin/prlimit',
                        '--as=268435456:268435456', '--cpu=60:60', '--fsize=67108864:67108864',
                        '--nofile=128:128', '--core=0:0', '--', '/usr/bin/python3',
                        '-E', '-s', '-B', str(VALIDATOR), '--artifact', temp,
                        '--revision', revision, '--sha256', digest], check=True,
                       stdin=subprocess.DEVNULL, timeout=120)
        if os.path.lexists(final):
            trusted(final)
            existing_fd = os.open(final, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                existing = os.fstat(existing_fd)
                if not stat.S_ISREG(existing.st_mode) or existing.st_uid != 0 or existing.st_nlink != 1:
                    raise Rejected('unsafe existing snapshot')
                current = hashlib.sha256()
                total = 0
                while True:
                    chunk = os.read(existing_fd, 65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise Rejected('existing snapshot too large')
                    current.update(chunk)
                if current.hexdigest() != digest or total != size:
                    raise Rejected('existing snapshot digest mismatch')
            finally:
                os.close(existing_fd)
        else:
            # A hard link is an atomic no-replace publication on the same filesystem.
            os.link(temp, final, follow_symlinks=False)
        os.unlink(temp)
        temp = None
        print(f'RECEIVE_OK\nREVISION={revision}\nSHA256={digest}\nSIZE={size}')
        return revision, digest
    finally:
        if temp is not None:
            os.unlink(temp)
        if lifecycle_fd is None:
            os.close(lock)


def main():
    if len(sys.argv) != 1 or os.geteuid() != 0:
        print('ERROR: invalid invocation', file=sys.stderr)
        return 1
    try:
        accept(0)
    except (OSError, ValueError, Rejected, ReceiveError, subprocess.SubprocessError) as error:
        print(f'ERROR: reception failed ({type(error).__name__})', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
