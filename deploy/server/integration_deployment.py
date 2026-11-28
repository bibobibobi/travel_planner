#!/usr/bin/python3
"""Exercise 3A against isolated systemd service and HTTP fixture."""
import contextlib
import io
import os
import pwd
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import deployment_controller as controller
import deployment_health as health
import deployment_transaction as transaction
import receive_artifact as intake

mount, app_user, outsider, unit = sys.argv[1:]
mount = Path(mount)
assert os.geteuid() == 0 and mount.parent == Path('/run')
assert mount.name.startswith('travel-deploy-test.') and mount.is_dir()
assert pwd.getpwnam(app_user).pw_uid != 0 and pwd.getpwnam(outsider).pw_uid != 0
slow_unit = unit.removesuffix('.service') + '-slow.service'
root = mount / 'app'
root.mkdir(mode=0o755)
for name in ('releases', 'shared', 'deployment-state'):
    (root / name).mkdir(mode=0o700 if name == 'deployment-state' else 0o755)
(root / 'shared' / '.env').write_text('TEST_SECRET=fixture\n', encoding='ascii')
app_account = pwd.getpwnam(app_user)
os.chown(root / 'shared', 0, app_account.pw_gid)
os.chmod(root / 'shared', 0o750)
os.chown(root / 'shared/.env', 0, app_account.pw_gid)
os.chmod(root / 'shared/.env', 0o640)
(root / 'shared' / 'uploads').mkdir()
os.chown(root / 'shared/uploads', app_account.pw_uid, app_account.pw_gid)
os.chmod(root / 'shared/uploads', 0o750)
(root / 'shared' / 'uploads' / 'fixture').write_bytes(b'permanent-test-data')
assert (root / 'shared').stat().st_uid == 0 and (root / 'shared').stat().st_mode & 0o777 == 0o750
assert (root / 'shared/.env').stat().st_uid == 0 and (root / 'shared/.env').stat().st_mode & 0o777 == 0o640
assert (root / 'shared/uploads').stat().st_uid == app_account.pw_uid
assert (root / 'shared/uploads').stat().st_mode & 0o777 == 0o750
(root / 'runtime').mkdir(mode=0o700)
os.chown(root / 'runtime', app_account.pw_uid, app_account.pw_gid)
lock = root / '.lifecycle.lock'
lock.touch(mode=0o644)
controller.ROOT = intake.ROOT = root
controller.RELEASES = root / 'releases'
controller.STATE = root / 'deployment-state'
controller.CURRENT = root / 'current'
controller.SERVICE = health.SERVICE = unit
controller.SERVICE_USER = app_user
intake.LOCK = lock

sock = socket.socket()
sock.bind(('127.0.0.1', 0))
port = sock.getsockname()[1]
sock.close()
health_file = mount / 'tools/deployment_health.py'
health_source = health_file.read_text(encoding='utf-8')
health_source = health_source.replace('http://127.0.0.1:5001', f'http://127.0.0.1:{port}')
health_source = health_source.replace('https://bobo-travel-planner.duckdns.org', f'http://127.0.0.1:{port}')
health_file.write_text(health_source, encoding='utf-8')


def make_release(revision, behavior, ready=True):
    path = root / 'releases' / revision
    (path / 'dist').mkdir(parents=True)
    (path / 'venv/bin').mkdir(parents=True)
    for name, content in {'app.py': b'app', 'websocket_worker.py': b'worker',
                          'requirements.txt': b'req', 'requirements-prod.txt': b'req',
                          'dist/index.html': b'<html>', 'REVISION': (revision + '\n').encode(),
                          'behavior': (behavior + '\n').encode(), 'venv/bin/pip': b'pip',
                          'venv/bin/gunicorn': b'gunicorn'}.items():
        file = path / name
        file.write_bytes(content)
        file.chmod(0o555 if name.startswith('venv/bin/') else 0o444)
    (path / 'venv/bin/python').symlink_to('/usr/bin/python3')
    (path / '.env').symlink_to(root / 'shared/.env')
    (path / 'uploads').symlink_to(root / 'shared/uploads')
    if ready:
        (path / '.release-ready').write_text(f'REVISION={revision}\nSHA256={"d" * 64}\n', encoding='ascii')
        (path / '.release-ready').chmod(0o444)
    return path


def locked(function, *args):
    fd = intake.take_lock(timeout=3)
    try:
        return function(*args)
    finally:
        os.close(fd)


def failure(function, text, *args):
    try:
        locked(function, *args)
    except (controller.DeploymentError, transaction.TransactionError) as error:
        assert text in str(error), str(error)
    else:
        raise AssertionError('expected rejection: ' + text)


def cli(*args):
    previous = sys.argv
    output, errors = io.StringIO(), io.StringIO()
    try:
        sys.argv = ['deployment_controller.py', *args]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = controller.main()
    finally:
        sys.argv = previous
    return code, output.getvalue(), errors.getvalue()


old, good, unhealthy, startfail = ('a' * 40, 'b' * 40, 'c' * 40, 'd' * 40)
incomplete, untrusted = 'e' * 40, 'f' * 40
interrupt_target = '1' * 40
make_release(old, 'healthy', ready=False)
make_release(good, 'healthy')
make_release(unhealthy, 'badhealth')
make_release(startfail, 'startfail')
make_release(incomplete, 'healthy', ready=False)
untrusted_path = make_release(untrusted, 'healthy')
make_release(interrupt_target, 'healthy')
os.chmod(untrusted_path / 'app.py', 0o666)
(root / 'current').symlink_to('releases/' + old)
subprocess.run(['/usr/bin/systemd-run', '--quiet', '--unit', unit, '--property=Type=simple',
                f'--property=User={app_user}', f'--property=WorkingDirectory={root / "current"}',
                '--property=Restart=no', '/usr/bin/python3',
                str(mount / 'tools/integration_http_service.py'), str(root), str(port)], check=True)
locked(controller.initialize, old)
code, output, errors = cli('deploy', good)
assert code == 0 and 'DEPLOY_OK' in output, errors
assert controller.current_revision() == good
state = controller.open_store().load()
assert state['current'] == good and state['previous'] == old and state['transaction'] is None
failure(controller.deploy, 'not ready', incomplete)
failure(controller.deploy, 'unsafe release file', untrusted)
failure(controller.deploy, 'rollback succeeded', startfail)
assert controller.current_revision() == good
code, output, errors = cli('deploy', unhealthy)
assert code != 0 and 'ROLLBACK_OK' in output and 'rollback succeeded' in errors
assert controller.current_revision() == good

# Exercise unsuccessful rollback, then explicit recovery after restoring health.
(root / 'block-old').write_text('block', encoding='ascii')
code, output, errors = cli('deploy', unhealthy)
assert code != 0 and 'ROLLBACK_OK' not in output and 'rollback health check failed' in errors
store = controller.open_store()
assert store.load()['transaction'] is not None
(root / 'block-old').unlink()
assert locked(controller.recover_if_needed, store)
assert controller.current_revision() == good

# Kill after durable pending state, immediately before and after symlink switch.
for after_switch in (False, True):
    pid = os.fork()
    if pid == 0:
        original = controller.switch
        def interrupt(revision, switch_first=after_switch, switch=original):
            if switch_first:
                switch(revision)
            os.kill(os.getpid(), signal.SIGKILL)
        controller.switch = interrupt
        locked(controller.deploy, interrupt_target)
        os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    assert locked(controller.recover_if_needed, store)
    assert controller.current_revision() == good

# The production health subprocess must enforce the deadline against a slow peer.
assert health.healthy(total_timeout=20, attempts=3)
slow_marker = root / 'runtime/slow-received'
slow_marker.unlink(missing_ok=True)
health_file.write_text(health_source.replace('/api/health', '/slow'), encoding='utf-8')
started = time.monotonic()
assert not health.healthy(total_timeout=2, attempts=1)
assert time.monotonic() - started < 4
assert slow_marker.read_text(encoding='ascii') == 'received\n'
health_file.write_text(health_source, encoding='utf-8')
assert health.healthy(total_timeout=20, attempts=3)

# Cross-process lock contention uses the same lock as backup/deployment.
held = intake.take_lock()
pid = os.fork()
if pid == 0:
    os.close(held)
    try:
        intake.take_lock(timeout=0.2)
    except intake.Rejected:
        os._exit(0)
    os._exit(1)
_, status = os.waitpid(pid, 0)
os.close(held)
assert os.waitstatus_to_exitcode(status) == 0

def permission_denied(code, target):
    script = ('import os,sys\ntry:\n ' + code + '\nexcept PermissionError:\n sys.exit(0)\n'
              'raise SystemExit("unexpectedly permitted")\n')
    check = subprocess.run(['/usr/sbin/runuser', '-u', outsider, '--', '/usr/bin/python3', '-c',
                            script, str(target)], check=False, cwd='/', capture_output=True)
    assert check.returncode == 0, check.stderr


for target in (root / 'current', root / 'shared/.env'):
    permission_denied('os.unlink(sys.argv[1])', target)
permission_denied("open(sys.argv[1], 'rb').read()", root / 'shared/.env')
permission_denied("open(sys.argv[1], 'wb').write(b'alter')", root / 'shared/.env')
permission_denied("open(sys.argv[1], 'wb').write(b'alter')", root / 'shared/uploads/fixture')
permission_denied("os.symlink('releases/' + 'b' * 40, sys.argv[1])", root / 'current-unauthorized')
assert (root / 'shared/.env').read_text(encoding='ascii') == 'TEST_SECRET=fixture\n'
assert (root / 'shared/uploads/fixture').read_bytes() == b'permanent-test-data'
assert (root / 'releases' / old).is_dir()
assert controller.current_revision() == good
app_read = subprocess.run(['/usr/sbin/runuser', '-u', app_user, '--', '/usr/bin/cat', str(root / 'shared/.env')],
                          cwd='/', capture_output=True, check=False)
assert app_read.returncode == 0 and app_read.stdout == b'TEST_SECRET=fixture\n'
upload = root / 'shared/uploads/app-write'
app_write = subprocess.run(['/usr/sbin/runuser', '-u', app_user, '--', '/usr/bin/python3', '-c',
                            "import sys; open(sys.argv[1], 'wb').write(b'app-data')", str(upload)],
                           cwd='/', capture_output=True, check=False)
assert app_write.returncode == 0 and upload.read_bytes() == b'app-data'

# A real systemd start job remains outstanding after the systemctl client times
# out. The transaction must remain pending and recovery must not switch current.
previous_state = store.load()
assert previous_state['transaction'] is None
state = dict(previous_state)
state['transaction'] = {'old': good, 'new': unhealthy}
store.save(state)
subprocess.run(['/usr/bin/systemd-run', '--no-block', '--quiet', '--unit', slow_unit,
                '--property=Type=notify', '--property=TimeoutStartSec=30s', f'--property=User={app_user}',
                '/usr/bin/python3', '-c', 'import time; time.sleep(30)'], check=True)
original_service, original_timeout = controller.SERVICE, controller.RESTART_TIMEOUT
try:
    controller.SERVICE = slow_unit
    controller.RESTART_TIMEOUT = 0.5
    try:
        locked(controller.restart_and_check)
    except controller.RestartUncertain as error:
        assert 'uncertain' in str(error)
    else:
        raise AssertionError('timed-out systemd restart unexpectedly succeeded')
    assert store.load()['transaction']['restart_uncertain'] is True
    before = os.readlink(root / 'current')
    code, output, errors = cli('recover')
    assert code != 0 and 'uncertain' in errors and 'ROLLBACK_OK' not in output
    assert os.readlink(root / 'current') == before
    subprocess.run(['/bin/systemctl', 'stop', slow_unit], timeout=20, check=True)
    assert controller.no_service_jobs()
    # Test-only reset, after the isolated job is confirmed stopped. This is not
    # an operational recovery procedure for an uncertain production job.
    store.save(previous_state)
finally:
    controller.SERVICE, controller.RESTART_TIMEOUT = original_service, original_timeout
assert health.healthy(total_timeout=20, attempts=3)
assert controller.current_revision() == good
print('DEPLOYMENT_INTEGRATION_OK')
