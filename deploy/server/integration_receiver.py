#!/usr/bin/python3
"""Root-run integration checks in a disposable, explicitly supplied test directory."""
import gzip
import hashlib
import io
import multiprocessing
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import receive_artifact as receiver

work = Path(sys.argv[1]).resolve(strict=True)
repo = Path(sys.argv[2]).resolve(strict=True)
user = sys.argv[3]
assert os.geteuid() == 0 and work.name.startswith('receiver-test-')
assert work.is_dir() and not work.is_symlink() and not list(work.iterdir())
account = pwd.getpwnam(user)
assert account.pw_uid != 0 and user != 'nobody'
os.chown(work, 0, 0)
os.chmod(work, 0o755)
root = work / 'app'
config = work / 'config'
root.mkdir(mode=0o755)
config.mkdir(mode=0o700)
for name in ('incoming', 'staging', 'build-inputs', 'artifact-snapshots', 'tools'):
    (root / name).mkdir(mode=0o755)
snapshots = root / 'artifact-snapshots'
os.chown(snapshots, 0, account.pw_gid)
os.chmod(snapshots, 0o710)
validator = root / 'tools/validate_artifact.py'
shutil.copyfile(repo / 'scripts/validate_artifact.py', validator)
os.chmod(validator, 0o755)
lock = root / '.lifecycle.lock'
lock.touch(mode=0o644)
receiver.ROOT, receiver.CONFIG, receiver.SNAPSHOTS, receiver.LOCK, receiver.VALIDATOR = (
    root, config, snapshots, lock, validator)
receiver.MIN_FREE = 0
receiver.VALIDATOR_USER = user
real_getpwnam = pwd.getpwnam
receiver.pwd.getpwnam = lambda name: real_getpwnam('nobody' if name == 'travel-deploy' else name)
def test_trusted(path, directory=False):
    # The real home is user-owned; validate all test components up to the
    # root-owned test directory instead of pretending its parent is trusted.
    current = path
    while True:
        info = current.lstat()
        isdir = current != path or directory
        assert (stat.S_ISDIR(info.st_mode) if isdir else stat.S_ISREG(info.st_mode))
        assert info.st_uid == 0 and not info.st_mode & 0o022
        assert not stat.S_ISREG(info.st_mode) or info.st_nlink == 1
        if current == work:
            return
        current = current.parent


receiver.trusted = test_trusted
rev = 'a' * 40
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
    for name, data in {'app.py': b'app', 'websocket_worker.py': b'worker',
                       'requirements.txt': b'flask', 'requirements-prod.txt': b'gunicorn',
                       'REVISION': (rev + '\n').encode(), 'dist/index.html': b'html',
                       'dist/app.js': b'js'}.items():
        entry = tarfile.TarInfo(name)
        entry.size = len(data)
        archive.addfile(entry, io.BytesIO(data))
artifact = buffer.getvalue()
digest = hashlib.sha256(artifact).hexdigest()
(config / 'allowed-artifacts').write_text(f'{rev} {digest}\n', encoding='ascii')
os.chmod(config / 'allowed-artifacts', 0o600)


def attempt(data, revision=rev, checksum=digest):
    r, w = os.pipe()
    def send():
        try:
            with os.fdopen(w, 'wb') as stream:
                stream.write(f'{revision} {checksum}\n'.encode() + data)
        except BrokenPipeError:
            pass
    writer = threading.Thread(target=send)
    writer.start()
    try:
        receiver.accept(r)
    finally:
        os.close(r)
        writer.join()


def rejected(data, expected_type, message, revision=rev, checksum=digest):
    try:
        attempt(data, revision, checksum)
    except expected_type as error:
        if message not in str(error):
            raise AssertionError(f'wrong rejection: {error}') from error
        return error
    raise AssertionError('expected rejection')


rejected(artifact, receiver.Rejected, 'invalid header', revision='A' * 40)
rejected(artifact, receiver.Rejected, 'not authorized', checksum='0' * 64)
rejected(b'', receiver.ReceiveError, 'empty artifact')
bad = b'not an artifact'
bad_digest = hashlib.sha256(bad).hexdigest()
(config / 'mode').write_text('trusted-ci\n', encoding='ascii')
os.chmod(config / 'mode', 0o600)
rejected(artifact, receiver.ReceiveError, 'SHA256 mismatch', checksum='0' * 64)
rejected(b'x' * (receiver.MAX_BYTES + 1), receiver.ReceiveError, 'artifact too large',
         checksum='0' * 64)
rejected(bad, subprocess.CalledProcessError, 'returned non-zero exit status', checksum=bad_digest)
assert not list(snapshots.iterdir())
(config / 'mode').write_text('manual\n', encoding='ascii')
old_limit = receiver.LIMITS['incoming']
receiver.LIMITS['incoming'] = receiver.MAX_BYTES + 1
capacity_file = root / 'incoming' / 'capacity-probe'
capacity_file.write_bytes(b'xx')
assert receiver.usage(root / 'incoming') == 2
rejected(artifact, receiver.Rejected, 'capacity limit exceeded')
capacity_file.unlink()
receiver.LIMITS['incoming'] = old_limit

# Exercise the full receiver with a valid header and a stalled body. The real
# stream reader is retained; only its timeout is shortened for this test.
original_receive = receiver.receive
receiver.receive = lambda fd, output, revision, checksum: original_receive(
    fd, output, revision, checksum, timeout=0.1)
r, w = os.pipe()
os.write(w, f'{rev} {digest}\n'.encode() + b'partial')
try:
    try:
        receiver.accept(r)
        raise AssertionError('receiver accepted a stalled stream')
    except receiver.ReceiveError as error:
        assert str(error) == 'upload timed out'
finally:
    receiver.receive = original_receive
    os.close(r)
    os.close(w)
assert not list(snapshots.glob('.incoming-*'))

attempt(artifact)
final = snapshots / f'{rev}-{digest}.tar.gz'
assert final.read_bytes() == artifact
assert final.stat().st_uid == 0 and stat.S_IMODE(final.stat().st_mode) == 0o440
check = subprocess.run(['/usr/sbin/runuser', '-u', user, '--', '/usr/bin/test', '-w', str(final)],
                       check=False)
assert check.returncode != 0
rejected(artifact, receiver.Rejected, 'snapshot already exists')
assert not list(snapshots.glob('.incoming-*'))

# Pass an already-open directory descriptor so a private /home ancestor does
# not cause misleading denials before the snapshot directory is reached.
nobody = real_getpwnam('nobody')
scratch = root / 'nobody-scratch'
scratch.mkdir(mode=0o777)
os.chmod(scratch, 0o777)
directory_fd = os.open(snapshots, os.O_RDONLY | os.O_DIRECTORY)
scratch_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)
try:
    program = r'''
import errno, os, sys
fd, scratch_fd, name = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
def denied(label, operation):
    try:
        operation()
    except OSError as error:
        if error.errno not in (errno.EACCES, errno.EPERM):
            raise AssertionError(f'{label}: unexpected errno {error.errno}') from error
    else:
        raise AssertionError(f'{label}: unexpectedly allowed')
denied('read', lambda: os.open(name, os.O_RDONLY, dir_fd=fd))
denied('modify', lambda: os.open(name, os.O_WRONLY | os.O_TRUNC, dir_fd=fd))
denied('delete', lambda: os.unlink(name, dir_fd=fd))
source = os.open('replacement', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=scratch_fd)
os.close(source)
denied('replace', lambda: os.rename('replacement', name, src_dir_fd=scratch_fd, dst_dir_fd=fd))
'''
    def become_nobody():
        os.setgroups([])
        os.setgid(nobody.pw_gid)
        os.setuid(nobody.pw_uid)
    subprocess.run(['/usr/bin/python3', '-c', program, str(directory_fd), str(scratch_fd), final.name],
                   preexec_fn=become_nobody, pass_fds=(directory_fd, scratch_fd), check=True)
finally:
    os.close(directory_fd)
    os.close(scratch_fd)
assert final.read_bytes() == artifact

(config / 'mode').write_text('trusted-ci\n', encoding='ascii')
ci_artifact = gzip.compress(gzip.decompress(artifact), mtime=1)
ci_digest = hashlib.sha256(ci_artifact).hexdigest()
assert ci_digest != digest
attempt(ci_artifact, checksum=ci_digest)
assert (snapshots / f'{rev}-{ci_digest}.tar.gz').read_bytes() == ci_artifact

# Real competing process must time out while this process holds the lock.
held = receiver.take_lock()
def contend(queue):
    try:
        receiver.take_lock(timeout=0.2)
    except receiver.Rejected:
        queue.put('blocked')
queue = multiprocessing.Queue()
process = multiprocessing.Process(target=contend, args=(queue,))
process.start()
process.join(5)
assert process.exitcode == 0 and queue.get(timeout=1) == 'blocked'
os.close(held)

# Capacity walker rejects filesystem links and FIFOs without opening them.
probe = root / 'incoming' / 'probe'
for kind in ('symlink', 'fifo', 'hardlink'):
    if kind == 'symlink':
        probe.symlink_to(final)
    elif kind == 'fifo':
        os.mkfifo(probe)
    else:
        original = root / 'incoming' / 'original'
        original.write_bytes(b'x')
        os.link(original, probe)
    try:
        receiver.usage(root / 'incoming')
        raise AssertionError(f'{kind} accepted')
    except receiver.Rejected:
        pass
    probe.unlink()
    if kind == 'hardlink':
        original.unlink()
print('RECEIVER_INTEGRATION_OK')
print('Test directory retained:', work)
