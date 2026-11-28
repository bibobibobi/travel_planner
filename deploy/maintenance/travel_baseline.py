#!/usr/bin/python3
"""Create a legacy package inventory from static dist-info metadata, as root."""
import email.parser
import fcntl
import os
import re
import sys
import tempfile
import time

import travel_backup_guard as guard

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\Z')
VERSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9.!+_-]*\Z')


def baseline():
    lock_path = guard.ROOT / '.lifecycle.lock'
    guard.trusted(lock_path)
    fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info, expected = os.fstat(fd), lock_path.stat()
        if (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino):
            raise guard.GuardError('lock changed')
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise guard.GuardError('lock timed out')
                time.sleep(0.1)
        release = guard.healthy_release()
        venv = release / 'venv'
        guard.trusted(venv, directory=True)
        lib = venv / 'lib'
        guard.trusted(lib, directory=True)
        sites = []
        for entry in lib.iterdir():
            if re.fullmatch(r'python3\.\d+', entry.name):
                guard.trusted(entry, directory=True)
                site = entry / 'site-packages'
                guard.trusted(site, directory=True)
                sites.append(site)
        if len(sites) != 1:
            raise guard.GuardError('expected one site-packages directory')
        packages = []
        metadata_bytes = 0
        seen = set()
        for entry in sites[0].iterdir():
            if entry.name.endswith('.egg-info'):
                raise guard.GuardError('legacy egg-info requires manual review')
            if not entry.name.endswith('.dist-info'):
                continue
            if len(packages) >= 10000:
                raise guard.GuardError('too many distributions')
            guard.trusted(entry, directory=True)
            data = guard.read_file(entry / 'METADATA', 1024 * 1024)
            metadata_bytes += len(data)
            if metadata_bytes > 50 * 1024 * 1024:
                raise guard.GuardError('total metadata limit exceeded')
            metadata = email.parser.BytesParser().parsebytes(data, headersonly=True)
            names, versions = metadata.get_all('Name', []), metadata.get_all('Version', [])
            if len(names) != 1 or len(versions) != 1 or not NAME.fullmatch(names[0]) or not VERSION.fullmatch(versions[0]):
                raise guard.GuardError('invalid distribution metadata')
            normalized = re.sub(r'[-_.]+', '-', names[0]).lower()
            if normalized in seen:
                raise guard.GuardError('duplicate distribution name')
            seen.add(normalized)
            packages.append(f'{names[0]}=={versions[0]}')
        if not packages:
            raise guard.GuardError('no static distribution metadata')
        payload = ('\n'.join(sorted(packages)) + '\n').encode('utf-8')
        if len(payload) > guard.MAX_PACKAGES:
            raise guard.GuardError('inventory too large')
        descriptor, name = tempfile.mkstemp(prefix='.baseline-', dir=venv)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                os.fchmod(output.fileno(), 0o444)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.link(name, venv / 'BUILD-PACKAGES.txt', follow_symlinks=False)
            directory = os.open(venv, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(name)
    finally:
        os.close(fd)


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        print('ERROR: invalid baseline invocation', file=sys.stderr)
        return 1
    try:
        baseline()
    except (guard.GuardError, OSError, ValueError) as error:
        print(f'ERROR: baseline failed: {type(error).__name__}', file=sys.stderr)
        return 1
    print('BASELINE_OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
