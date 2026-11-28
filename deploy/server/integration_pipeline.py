#!/usr/bin/python3
"""Root-run isolated end-to-end pipeline test with real validator, builder and service."""
import contextlib
import hashlib
import io
import os
import pwd
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import deploy_pipeline as pipeline
import deployment_controller as controller
import deployment_health as health
import receive_artifact as receiver
import release_builder as builder

mount, build_user, app_user, deploy_user, unit, prefix, port, mode = sys.argv[1:]
mount = Path(mount)
port = int(port)
assert mode in ('', '--recovery-only')
assert os.geteuid() == 0 and mount.parent == Path('/run')
assert mount.name.startswith('travel-pipeline-test.') and mount.is_dir()
root = mount / 'app'
root.mkdir(mode=0o755)
for name in ('incoming', 'staging', 'build-inputs', 'releases', 'build-work',
             'artifact-snapshots', 'shared', 'deployment-state', 'config'):
    (root / name).mkdir(mode=0o700 if name in ('deployment-state', 'config') else 0o755)
os.chmod(root / 'build-work', 0o711)
build_account, app_account, deploy_account = (pwd.getpwnam(name) for name in (build_user, app_user, deploy_user))
os.chown(root / 'artifact-snapshots', 0, build_account.pw_gid)
os.chmod(root / 'artifact-snapshots', 0o710)
os.chown(root / 'shared', 0, app_account.pw_gid)
os.chmod(root / 'shared', 0o750)
(root / 'shared/.env').write_text('TEST_SECRET=fixture\n', encoding='ascii')
os.chown(root / 'shared/.env', 0, app_account.pw_gid)
os.chmod(root / 'shared/.env', 0o640)
(root / 'shared/uploads').mkdir(mode=0o750)
os.chown(root / 'shared/uploads', app_account.pw_uid, app_account.pw_gid)
lock = root / '.lifecycle.lock'
lock.touch(mode=0o644)
os.chown(lock, 0, deploy_account.pw_gid)
os.chmod(lock, 0o640)

receiver.ROOT = builder.ROOT = controller.ROOT = root
receiver.LOCK = lock
receiver.CONFIG = root / 'config'
receiver.SNAPSHOTS = builder.SNAPSHOTS = root / 'artifact-snapshots'
receiver.VALIDATOR = mount / 'tools/validate_artifact.py'
receiver.VALIDATOR_USER = build_user
real_getpwnam = pwd.getpwnam
receiver.pwd.getpwnam = lambda name: real_getpwnam(deploy_user if name == 'travel-deploy' else name)
builder.RELEASES = controller.RELEASES = root / 'releases'
builder.WORK = root / 'build-work'
builder.SHARED = root / 'shared'
builder.EXTRACTOR = mount / 'tools/extract_artifact.py'
builder.WORKER = mount / 'tools/release_build_worker.py'
builder.BUILDER = build_user
builder.UNIT_PREFIX = prefix
builder.FREE_BYTES = 200 * 1024 * 1024
controller.CURRENT = root / 'current'
controller.STATE = root / 'deployment-state'
controller.SERVICE = health.SERVICE = unit
controller.SERVICE_USER = app_user

health_file = mount / 'tools/deployment_health.py'
source = health_file.read_text(encoding='utf-8')
source = source.replace('http://127.0.0.1:5001', f'http://127.0.0.1:{port}')
source = source.replace('https://bobo-travel-planner.duckdns.org', f'http://127.0.0.1:{port}')
health_file.write_text(source, encoding='utf-8')


def artifact(revision, behavior, requirements=b'gunicorn==23.0.0\n'):
    data = io.BytesIO()
    files = {'app.py': (behavior + '\n').encode(), 'websocket_worker.py': b'worker',
             'requirements.txt': b'gunicorn==23.0.0\n', 'requirements-prod.txt': requirements,
             'REVISION': (revision + '\n').encode(), 'dist/index.html': b'<html>', 'dist/app.js': b'js'}
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    raw = data.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def fixture_release(revision, behavior, digest=None):
    path = root / 'releases' / revision
    (path / 'dist').mkdir(parents=True)
    (path / 'venv/bin').mkdir(parents=True)
    files = {'app.py': (behavior + '\n').encode(), 'websocket_worker.py': b'worker',
             'requirements.txt': b'req', 'requirements-prod.txt': b'req', 'dist/index.html': b'<html>',
             'REVISION': (revision + '\n').encode(), 'venv/bin/pip': b'pip', 'venv/bin/gunicorn': b'gunicorn'}
    for name, content in files.items():
        target = path / name
        target.write_bytes(content)
        target.chmod(0o555 if name.startswith('venv/bin/') else 0o444)
    (path / 'venv/bin/python').symlink_to('/usr/bin/python3')
    (path / '.env').symlink_to(root / 'shared/.env')
    (path / 'uploads').symlink_to(root / 'shared/uploads')
    if digest:
        marker = path / '.release-ready'
        marker.write_text(f'REVISION={revision}\nSHA256={digest}\n', encoding='ascii')
        marker.chmod(0o444)


def invoke(raw, revision, digest):
    read_fd, write_fd = os.pipe()
    def send():
        try:
            with os.fdopen(write_fd, 'wb') as stream:
                stream.write(f'{revision} {digest}\n'.encode() + raw)
        except BrokenPipeError:
            pass
    writer = threading.Thread(target=send)
    writer.start()
    output = io.StringIO()
    try:
        try:
            with contextlib.redirect_stdout(output):
                pipeline.run(read_fd)
        except (pipeline.PipelineError, controller.DeploymentError, receiver.ReceiveError,
                receiver.Rejected, subprocess.CalledProcessError, builder.BuildError) as error:
            error.pipeline_output = output.getvalue()
            raise
    finally:
        os.close(read_fd)
        writer.join()
    return output.getvalue()


def rejected(raw, revision, digest, expected, message):
    try:
        invoke(raw, revision, digest)
    except expected as error:
        assert message in str(error), str(error)
        assert 'DEPLOY_OK' not in error.pipeline_output
        if 'rollback succeeded' in message:
            assert 'ROLLBACK_OK' in error.pipeline_output
    else:
        raise AssertionError('expected pipeline failure: ' + message)


old, new, bad, invalid, wrong_rev, incomplete = ('a' * 40, 'b' * 40, 'c' * 40,
                                                   'd' * 40, 'e' * 40, 'f' * 40)
if mode == '--recovery-only':
    fixture_release(old, 'healthy')
    fixture_release(bad, 'badhealth', 'd' * 64)
    (root / 'current').symlink_to('releases/' + old)
    subprocess.run(['/bin/systemctl', 'start', unit], check=True, timeout=30)
    fd = receiver.take_lock()
    try:
        controller.initialize(old)
        store = controller.open_store()
        state = store.load()
        state['transaction'] = {'old': old, 'new': bad, 'restart_uncertain': True}
        store.save(state)
        controller.recover_uncertain()
    finally:
        os.close(fd)
    assert store.load()['transaction'] is None and controller.current_revision() == old
    assert health.healthy() and controller.service_matches_current(old)
    print('RECOVERY_SCENARIOS_OK')
    sys.exit(0)

raw, digest = artifact(new, 'healthy')
other, other_digest = artifact(new, 'badhealth')
bad_raw, bad_digest = artifact(bad, 'badhealth')
invalid_raw, invalid_digest = artifact(invalid, 'healthy', b'not a valid requirement !!!\n')
incomplete_raw, incomplete_digest = artifact(incomplete, 'healthy')
allowlist = root / 'config/allowed-artifacts'
allowlist.write_text(''.join(f'{rev} {sha}\n' for rev, sha in [
    (new, digest), (new, other_digest), (new, '0' * 64), (wrong_rev, digest),
    (bad, bad_digest), (invalid, invalid_digest), (incomplete, incomplete_digest)]), encoding='ascii')
allowlist.chmod(0o600)
fixture_release(old, 'healthy')
fixture_release(bad, 'badhealth', bad_digest)
fixture_release(incomplete, 'healthy')
(root / 'current').symlink_to('releases/' + old)
subprocess.run(['/bin/systemctl', 'start', unit], check=True, timeout=30)
fd = receiver.take_lock()
try:
    controller.initialize(old)
finally:
    os.close(fd)
result = invoke(raw, new, digest)
assert 'RECEIVE_OK' in result and 'RELEASE_READY' in result and 'DEPLOY_OK' in result
assert controller.current_revision() == new
assert (root / 'releases' / new / 'venv/BUILD-PACKAGES.txt').is_file()
result = invoke(raw, new, digest)
assert 'RELEASE_REUSED' in result and 'ALREADY_DEPLOYED' in result and 'DEPLOY_OK' in result
rejected(other, new, other_digest, pipeline.PipelineError, 'digest mismatch')
rejected(raw, new, '0' * 64, receiver.ReceiveError, 'SHA256 mismatch')
rejected(raw, wrong_rev, digest, subprocess.CalledProcessError, 'non-zero exit status')
rejected(incomplete_raw, incomplete, incomplete_digest, controller.DeploymentError, 'not ready')
assert (root / 'releases' / incomplete).is_dir()
rejected(invalid_raw, invalid, invalid_digest, builder.BuildError, 'build worker failed')
assert not (root / 'releases' / invalid).exists()
assert controller.current_revision() == new
rejected(bad_raw, bad, bad_digest, controller.DeploymentError, 'rollback succeeded')
assert controller.current_revision() == new

# Explicit administrator recovery, using the real systemd stop/restart path.
store = controller.open_store()
state = store.load()
state['transaction'] = {'old': new, 'new': bad, 'restart_uncertain': True}
store.save(state)
fd = receiver.take_lock()
try:
    controller.recover_uncertain()
finally:
    os.close(fd)
assert store.load()['transaction'] is None and controller.current_revision() == new

# A non-root backup-style reader cannot replace the root-owned lock, and is
# excluded by the very same lifecycle lock while deployment holds it.
held = receiver.take_lock()
backup_probe = ("import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDONLY)\n"
                "try:\n fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
                "except BlockingIOError:\n sys.exit(0)\n"
                "sys.exit(1)\n")
probe = subprocess.run(['/usr/sbin/runuser', '-u', deploy_user, '--', '/usr/bin/python3',
                        '-c', backup_probe, str(lock)], cwd='/', capture_output=True, check=False)
assert probe.returncode == 0, probe.stderr
pid = os.fork()
if pid == 0:
    os.close(held)
    try:
        receiver.take_lock(timeout=0.2)
    except receiver.Rejected:
        os._exit(0)
    os._exit(1)
_, status = os.waitpid(pid, 0)
os.close(held)
assert os.waitstatus_to_exitcode(status) == 0
backup_probe = "import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDONLY); fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)"
probe = subprocess.run(['/usr/sbin/runuser', '-u', deploy_user, '--', '/usr/bin/python3',
                        '-c', backup_probe, str(lock)], cwd='/', capture_output=True, check=False)
assert probe.returncode == 0, probe.stderr
replace_probe = ("import os,sys\ntry:\n os.unlink(sys.argv[1])\nexcept PermissionError:\n sys.exit(0)\n"
                 "sys.exit(1)\n")
probe = subprocess.run(['/usr/sbin/runuser', '-u', deploy_user, '--', '/usr/bin/python3',
                        '-c', replace_probe, str(lock)], cwd='/', capture_output=True, check=False)
assert probe.returncode == 0, probe.stderr
assert (root / 'shared/.env').read_text(encoding='ascii') == 'TEST_SECRET=fixture\n'
print('PIPELINE_SCENARIOS_OK')
