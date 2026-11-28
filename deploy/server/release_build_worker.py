#!/usr/bin/python3
"""Unprivileged build worker; invoked only inside the controller's cgroup."""
import os
import subprocess
import sys
from pathlib import Path


def main():
    if os.geteuid() == 0 or not (len(sys.argv) == 2 or
                                  len(sys.argv) == 3 and sys.argv[1] == '--verify'):
        return 2
    verifying = len(sys.argv) == 3
    release = Path(sys.argv[-1])
    venv = release / 'venv'
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(venv), 'TMPDIR': '/tmp',
           'PIP_CONFIG_FILE': '/dev/null', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
           'PIP_NO_CACHE_DIR': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8'}
    commands = [] if verifying else [
        ['/usr/bin/python3', '-m', 'venv', str(venv)],
        [str(venv / 'bin/pip'), 'install', '--no-cache-dir', '--timeout', '30',
         '-r', str(release / 'requirements-prod.txt')],
    ]
    commands += [
        [str(venv / 'bin/pip'), 'check'],
        [str(venv / 'bin/python'), '--version'],
        [str(venv / 'bin/pip'), '--version'],
        [str(venv / 'bin/gunicorn'), '--version'],
    ]
    for command in commands:
        subprocess.run(command, env=env, cwd=release, stdin=subprocess.DEVNULL, check=True)
    if not verifying:
        # A package inventory avoids running release Python as backup/root.
        # Name/version metadata avoids recording authenticated index URLs.
        script = ("from importlib import metadata; "
                  "items=sorted((d.metadata.get('Name',''),d.version) for d in metadata.distributions()); "
                  "[print(n+'=='+v) for n,v in items if n]")
        with (venv / 'BUILD-PACKAGES.txt').open('x', encoding='utf-8') as output:
            subprocess.run([str(venv / 'bin/python'), '-c', script], env=env, cwd=release,
                           stdin=subprocess.DEVNULL, stdout=output, check=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
