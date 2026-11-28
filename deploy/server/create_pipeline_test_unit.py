#!/usr/bin/python3
"""Create exactly one no-overwrite, root-owned WSL pipeline test unit."""
import os
import re
import stat
import sys
from pathlib import Path


def main():
    if os.geteuid() != 0 or len(sys.argv) != 5:
        return 2
    unit_path, mount, user, port = sys.argv[1:]
    unit_path, mount = Path(unit_path), Path(mount)
    if (unit_path.parent != Path('/run/systemd/system') or
            not re.fullmatch(r'tptest[a-z0-9]{8}\.service', unit_path.name) or
            mount.parent != Path('/run') or
            not re.fullmatch(r'travel-pipeline-test\.[A-Za-z0-9]{8}', mount.name) or
            not re.fullmatch(r'tpa[a-z0-9]{8}', user) or
            not port.isdecimal() or not 1 <= int(port) <= 65535):
        return 2
    for directory in (unit_path.parent, mount, mount / 'tools'):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            return 2
    service = mount / 'tools/integration_http_service.py'
    info = service.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1:
        return 2
    payload = (f'[Unit]\nDescription=Isolated pipeline test {unit_path.name}\n'
               f'[Service]\nType=simple\nUser={user}\nWorkingDirectory={mount}/app/current\n'
               f'ExecStart=/usr/bin/python3 {service} {mount}/app {port}\n'
               'Restart=no\nKillMode=control-group\nTimeoutStopSec=15s\nSendSIGKILL=yes\n').encode('ascii')
    fd = os.open(unit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        info = os.fstat(fd)
        print(f'{info.st_dev}:{info.st_ino}')
    except OSError:
        current = unit_path.lstat()
        opened = os.fstat(fd)
        if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
            unit_path.unlink()
        raise
    finally:
        os.close(fd)
    return 0


if __name__ == '__main__':
    sys.exit(main())
