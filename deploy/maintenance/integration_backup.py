#!/usr/bin/python3
"""Root-only isolated filesystem integration; invoked by test-backup-root.sh."""
import fcntl
import grp
import json
import os
import pwd
import subprocess
import sys
import tarfile
from pathlib import Path

repo, work = map(Path, sys.argv[1:3])
group, backup, deploy, build, app = sys.argv[3:]
sys.path.insert(0, str(repo / 'deploy/maintenance'))
import travel_backup_guard as guard
import travel_baseline as baseline

root = work / 'app'
revision = 'a' * 40
release = root / 'releases' / revision
venv = release / 'venv'
site = venv / 'lib/python3.12/site-packages'
site.mkdir(parents=True)
state_dir = root / 'deployment-state'
state_dir.mkdir(mode=0o700)
state = state_dir / 'deployment-state.json'
state.write_text(json.dumps({'current': revision, 'previous': None, 'transaction': None}))
state.chmod(0o600)
(release / 'REVISION').write_text(revision + '\n')
(root / 'current').symlink_to('releases/' + revision)
lock = root / '.lifecycle.lock'
lock.touch(mode=0o640)
os.chown(lock, 0, grp.getgrnam(group).gr_gid)
guard.ROOT, guard.STATE, guard.CURRENT = root, state, root / 'current'
dist = site / 'Fixture-1.0.dist-info'
dist.mkdir()
(dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: Fixture\nVersion: 1.0\n\n')
marker = work / 'release-python-ran'
(venv / 'bin').mkdir()
python = venv / 'bin/python'
python.write_text('#!/bin/sh\ntouch ' + str(marker) + '\nexit 99\n')
python.chmod(0o755)
baseline.baseline()
inventory = venv / 'BUILD-PACKAGES.txt'
assert guard.current_packages() == b'Fixture==1.0\n'
assert inventory.stat().st_mode & 0o777 == 0o444
try:
    baseline.baseline()
except FileExistsError:
    pass
else:
    raise AssertionError('baseline overwrote an existing inventory')


def rejected(fn, reason):
    try:
        fn()
    except (guard.GuardError, OSError, ValueError) as error:
        assert reason in str(error), str(error)
    else:
        raise AssertionError('unsafe input accepted: ' + reason)


inventory.chmod(0o666)
rejected(guard.current_packages, 'permissions')
inventory.chmod(0o444)
extra = venv / 'hardlink'
os.link(inventory, extra)
rejected(guard.current_packages, 'hardlinked')
extra.unlink()
saved = venv / 'saved-inventory'
inventory.rename(saved)
inventory.symlink_to(saved.name)
rejected(guard.current_packages, 'file type')
inventory.unlink()
os.mkfifo(inventory)
rejected(guard.current_packages, 'file type')
inventory.unlink()
saved.rename(inventory)
state.write_text(json.dumps({'current': revision, 'previous': None, 'transaction': {'phase': 'restart_uncertain'}}))
rejected(guard.current_packages, 'pending')
state.write_text(json.dumps({'current': revision, 'previous': None, 'transaction': None}))
assert guard.current_packages() == b'Fixture==1.0\n'
assert not marker.exists(), 'Release Python was executed'

source = (repo / 'deploy/maintenance/backup.sh').read_text(encoding='utf-8').rstrip()
assert source.endswith('\nmain')
source = source[:-len('\nmain')] + '\n'
source = source.replace('TRAVEL_ROOT="/opt/travel-app"', f'TRAVEL_ROOT="{root}"')
source = source.replace('for account in travel-deploy travel-build travel-app; do',
                        f'for account in {deploy} {build} {app}; do')
source = source.replace('/usr/bin/flock -x -w 30 8', '/usr/bin/flock -x -w 1 8')
test_script = work / 'backup-test-copy.sh'
test_script.write_text(source, encoding='utf-8')
test_script.chmod(0o644)
home = work / 'backup-home'
home.mkdir(mode=0o700)
uid, gid = pwd.getpwnam(backup).pw_uid, pwd.getpwnam(backup).pw_gid
os.chown(home, uid, gid)


def as_user(user, command, *, check=True):
    return subprocess.run(['/usr/sbin/runuser', '-u', user, '--', '/usr/bin/env',
                           f'HOME={home}', '/bin/bash', '-c', command, 'test', str(test_script)],
                          text=True, capture_output=True, check=check, timeout=15)


for user in (deploy, build, app):
    result = as_user(user, f'test -r "{lock}"', check=False)
    assert result.returncode != 0, user

cmd = 'source "$1"; acquire_lifecycle_lock; echo LOCK_HELD; sleep 3'
process = subprocess.Popen(['/usr/sbin/runuser', '-u', backup, '--', '/usr/bin/env',
                            f'HOME={home}', '/bin/bash', '-c', cmd, 'test', str(test_script)],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    assert process.stdout.readline().strip() == 'Lifecycle lock acquired'
    assert process.stdout.readline().strip() == 'LOCK_HELD'
    fd = os.open(lock, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError('deployment acquired backup-held lock')
    finally:
        os.close(fd)
finally:
    out, err = process.communicate(timeout=10)
    assert process.returncode == 0, (out, err)

fd = os.open(lock, os.O_RDONLY)
fcntl.flock(fd, fcntl.LOCK_EX)
try:
    result = as_user(backup, 'source "$1"; acquire_lifecycle_lock', check=False)
    assert result.returncode and 'timed out' in result.stderr, result.stderr
finally:
    os.close(fd)
lock.unlink()
result = as_user(backup, 'source "$1"; acquire_lifecycle_lock', check=False)
assert result.returncode and 'missing or unsafe' in result.stderr, result.stderr

# Exercise the original verify, atomic publish and retention functions in isolation.
snapshots = home / 'snapshots'
snapshots.mkdir()
os.chown(snapshots, uid, gid)
temporary = snapshots / '.incomplete-20010101-000000-fixture'
temporary.mkdir()
os.chown(temporary, uid, gid)
archive = temporary / 'fixture.tar.gz'
with tarfile.open(archive, 'w:gz') as tar:
    tar.add(dist / 'METADATA', arcname='METADATA')
os.chown(archive, uid, gid)
for number in range(1, 9):
    previous = snapshots / f'20000101-{number:06d}'
    previous.mkdir()
    os.chown(previous, uid, gid)
    (previous / 'SHA256SUMS').write_text('fixture\n')
    os.chown(previous / 'SHA256SUMS', uid, gid)
destination = snapshots / '20010101-000000'
command = (f'source "$1"; TEMP_DIR="{temporary}"; BACKUP_ROOT="{snapshots}"; '
           f'BACKUP_DIR="{destination}"; verify_backup; publish_backup; rotate_backups')
result = as_user(backup, command)
assert (destination / 'SHA256SUMS').is_file() and not temporary.exists()
assert '[DRY RUN] Would remove:' in result.stdout
assert all((snapshots / f'20000101-{number:06d}').is_dir() for number in range(1, 9))
assert not marker.exists()
print('BACKUP_CHECKS_OK')
