"""Validate the build output and stream it to the fixed deployment entry."""
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
HOST = re.compile(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}\Z')
USER = re.compile(r'[a-z_][a-z0-9_-]{0,31}\Z')


def deploy(artifact, revision, expected, env):
    if not SHA.fullmatch(revision) or not DIGEST.fullmatch(expected):
        raise ValueError('invalid revision or digest')
    host, user = env['TRAVEL_DEPLOY_HOST'], env['TRAVEL_DEPLOY_USER']
    if not HOST.fullmatch(host) or not USER.fullmatch(user):
        raise ValueError('invalid SSH destination')
    path = Path(artifact)
    if not path.is_file() or path.is_symlink():
        raise ValueError('invalid artifact')
    with path.open('rb') as source:
        data = source.read(10 * 1024 * 1024 + 1)
    if not 0 < len(data) <= 10 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('artifact digest or size mismatch')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        entries = [entry for entry in archive if entry.name == 'REVISION']
        if len(entries) != 1 or not entries[0].isfile() or entries[0].size != 41:
            raise ValueError('invalid artifact revision')
        stream = archive.extractfile(entries[0])
        if stream is None or stream.read(42) != (revision + '\n').encode('ascii'):
            raise ValueError('artifact revision mismatch')
    with tempfile.TemporaryDirectory(prefix='travel-cd-') as directory:
        key, known = Path(directory) / 'key', Path(directory) / 'known_hosts'
        for file, secret in ((key, env['TRAVEL_DEPLOY_SSH_KEY']),
                             (known, env['TRAVEL_DEPLOY_KNOWN_HOSTS'])):
            fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
                output.write(secret.rstrip('\n') + '\n')
        args = ['ssh', '-F', '/dev/null', '-i', str(key), '-o', f'UserKnownHostsFile={known}',
                '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'ForwardAgent=no',
                '-o', 'ClearAllForwardings=yes', '-o', 'RequestTTY=no', '-o', 'ConnectTimeout=20',
                '-T', f'{user}@{host}', f'deploy-artifact {revision} {expected}']
        result = subprocess.run(args, input=data, capture_output=True, timeout=1500, check=False)
    lines = result.stdout.splitlines()
    if b'ROLLBACK_OK' in lines:
        raise ValueError('deployment failed; server reported ROLLBACK_OK')
    if result.returncode or lines.count(b'DEPLOY_OK') != 1:
        raise ValueError('SSH failed or DEPLOY_OK missing')
    print('DEPLOY_OK')


def main():
    if len(sys.argv) != 4:
        return 1
    try:
        deploy(sys.argv[1], sys.argv[2], sys.argv[3], os.environ)
    except (ValueError, OSError, KeyError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
