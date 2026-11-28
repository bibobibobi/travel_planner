#!/usr/bin/python3
"""Candidate root-only controller for already-built releases; no SSH entry."""
import os
import pwd
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import deployment_health as health
import deployment_transaction as transaction
import receive_artifact as intake
import release_tree

ROOT = Path('/opt/travel-app')
RELEASES = ROOT / 'releases'
STATE = ROOT / 'deployment-state'
CURRENT = ROOT / 'current'
SERVICE = 'travel.service'
SERVICE_USER = 'travel-app'
RESTART_TIMEOUT = 45
CGROUP_ROOT = Path('/sys/fs/cgroup')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class DeploymentError(RuntimeError):
    pass


class RestartUncertain(RuntimeError):
    """systemd may still have a pending restart; switching is forbidden."""


def read_trusted(path, limit):
    intake.trusted(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise DeploymentError('unsafe release metadata')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise DeploymentError('release metadata too large')
        return data
    finally:
        os.close(fd)


def validate_release(revision, *, allow_legacy=False):
    if not transaction.valid_revision(revision):
        raise DeploymentError('invalid revision')
    intake.trusted(RELEASES, directory=True)
    root = RELEASES / revision
    intake.trusted(root, directory=True)
    device = root.stat().st_dev
    required_links = {('.env',): str(ROOT / 'shared/.env'), ('uploads',): str(ROOT / 'shared/uploads')}
    seen_links = set()

    def walk_error(error):
        raise error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs[:] + files:
            path = Path(directory) / name
            info = path.lstat()
            parts = path.relative_to(root).parts
            if info.st_uid != 0 or info.st_dev != device:
                raise DeploymentError('untrusted release ownership or filesystem')
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                normalized = os.path.normpath(os.path.join(str(path.parent), target))
                if parts in required_links and normalized == required_links[parts]:
                    seen_links.add(parts)
                elif not release_tree.allowed_python_link(parts, target):
                    raise DeploymentError('unsafe release link')
                if name in dirs:
                    dirs.remove(name)
            elif stat.S_ISDIR(info.st_mode):
                if info.st_mode & 0o6022:
                    raise DeploymentError('writable release directory')
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o6022:
                raise DeploymentError('unsafe release file')
    if seen_links != set(required_links):
        raise DeploymentError('missing shared links')
    for name in ('app.py', 'websocket_worker.py', 'requirements.txt', 'requirements-prod.txt',
                 'dist/index.html', 'venv/bin/pip', 'venv/bin/gunicorn'):
        try:
            info = (root / name).lstat()
        except FileNotFoundError as error:
            raise DeploymentError('release missing required file') from error
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
            raise DeploymentError('invalid required release file')
        if name.startswith('venv/bin/') and not info.st_mode & 0o111:
            raise DeploymentError('release executable is not executable')
    if not (root / 'venv/bin/python').exists():
        raise DeploymentError('release python missing')
    if read_trusted(root / 'REVISION', 128) != (revision + '\n').encode('ascii'):
        raise DeploymentError('release revision mismatch')
    marker = root / '.release-ready'
    if not os.path.lexists(marker):
        if allow_legacy:
            return None
        raise DeploymentError('release is not ready')
    data = read_trusted(marker, 256)
    match = re.fullmatch(rb'REVISION=([0-9a-f]{40})\nSHA256=([0-9a-f]{64})\n', data)
    if not match or match.group(1).decode('ascii') != revision:
        raise DeploymentError('invalid release marker')
    return match.group(2).decode('ascii')


def current_revision():
    info = CURRENT.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise DeploymentError('current must be a symbolic link')
    target = CURRENT.resolve(strict=True)
    if target.parent != RELEASES or not transaction.valid_revision(target.name):
        raise DeploymentError('unsafe current target')
    return target.name


def switch(revision):
    if not transaction.valid_revision(revision):
        raise DeploymentError('invalid switch target')
    temporary = ROOT / ('.current-' + uuid.uuid4().hex)
    try:
        os.symlink('releases/' + revision, temporary)
        os.replace(temporary, CURRENT)
        fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def service_matches_current(revision):
    """Ensure the active systemd main process uses the selected release cwd."""
    try:
        result = subprocess.run(['/bin/systemctl', 'show', SERVICE, '--all', '--no-pager',
                                 '-p', 'MainPID', '-p', 'User', '-p', 'WorkingDirectory'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=5, check=True)
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        pid = int(fields.get('MainPID', '0'))
        if (pid <= 0 or fields.get('User') != SERVICE_USER or
                fields.get('WorkingDirectory') != str(CURRENT)):
            return False
        proc = Path('/proc') / str(pid)
        if proc.stat().st_uid != pwd.getpwnam(SERVICE_USER).pw_uid:
            return False
        return os.path.realpath(proc / 'cwd') == str(RELEASES / revision)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False


def no_service_jobs():
    """Fail closed unless systemd reports no job and a non-transitional state."""
    try:
        shown = subprocess.run(['/bin/systemctl', 'show', SERVICE, '--all', '--no-pager',
                                '-p', 'Job', '-p', 'ActiveState'], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=5, check=False)
        fields = dict(line.split('=', 1) for line in shown.stdout.splitlines() if '=' in line)
        jobs = subprocess.run(['/bin/systemctl', 'list-jobs', '--no-legend', '--plain', '--no-pager'],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=True)
        pending = any(SERVICE in line.split() for line in jobs.stdout.splitlines())
        if shown.returncode:
            listing = subprocess.run(['/bin/systemctl', 'list-units', '--all', '--no-legend', '--plain',
                                      '--no-pager', SERVICE], stdin=subprocess.DEVNULL, capture_output=True,
                                     text=True, timeout=5, check=True)
            return not pending and not any(SERVICE in line.split() for line in listing.stdout.splitlines())
        return (fields.get('Job') in ('', '0') and fields.get('ActiveState') in ('active', 'inactive', 'failed')
                and not pending)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def service_cgroup():
    """Identify the fixed, non-delegated service cgroup before stopping it."""
    if not re.fullmatch(r'[A-Za-z0-9_-]+\.service', SERVICE):
        raise RestartUncertain('invalid service name; pending transaction preserved')
    try:
        result = subprocess.run(['/bin/systemctl', 'show', SERVICE, '--all', '--no-pager',
                                 '-p', 'LoadState', '-p', 'Slice', '-p', 'Delegate',
                                 '-p', 'User', '-p', 'ControlGroup'], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=5, check=True)
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        expected = '/system.slice/' + SERVICE
        if (fields.get('LoadState') != 'loaded' or fields.get('Slice') != 'system.slice' or
                fields.get('Delegate') != 'no' or fields.get('User') != SERVICE_USER or
                fields.get('ControlGroup') not in ('', expected)):
            raise RestartUncertain('cannot establish service cgroup; pending transaction preserved')
        return CGROUP_ROOT / expected.lstrip('/')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise RestartUncertain('cannot establish service cgroup; pending transaction preserved') from error


def service_fully_stopped(cgroup):
    """Require stopped unit, no jobs, zero main PID and no cgroup processes."""
    try:
        result = subprocess.run(['/bin/systemctl', 'show', SERVICE, '--all', '--no-pager',
                                 '-p', 'LoadState', '-p', 'ActiveState', '-p', 'SubState',
                                 '-p', 'MainPID', '-p', 'ControlGroup', '-p', 'Slice', '-p', 'Delegate'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=False)
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        expected = '/system.slice/' + SERVICE
        if result.returncode or fields.get('LoadState') == 'not-found':
            # systemd may unload a stopped transient unit. Confirm independently
            # that the manager is reachable and the exact unit is absent.
            listing = subprocess.run(['/bin/systemctl', 'list-units', '--all', '--no-legend', '--plain',
                                      '--no-pager', SERVICE], stdin=subprocess.DEVNULL, capture_output=True,
                                     text=True, timeout=5, check=True)
            if any(SERVICE in line.split() for line in listing.stdout.splitlines()):
                return False
        elif (fields.get('LoadState') != 'loaded' or fields.get('ActiveState') not in ('inactive', 'failed') or
              fields.get('SubState') not in ('dead', 'failed') or fields.get('MainPID') != '0' or
              fields.get('Slice') != 'system.slice' or fields.get('Delegate') != 'no' or
              fields.get('ControlGroup') not in ('', expected)):
            return False
        if not no_service_jobs():
            return False
        try:
            events = dict(line.split() for line in (cgroup / 'cgroup.events').read_text(
                encoding='ascii').splitlines())
            empty = events.get('populated') == '0'
        except FileNotFoundError:
            empty = not cgroup.exists()
        return empty and no_service_jobs()
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def restart_and_check():
    store = open_store()
    state = store.load()
    if state['transaction'] is None or state['transaction'].get('restart_uncertain', False):
        raise RestartUncertain('restart job status uncertain; pending transaction preserved')
    # Persist before submitting: SIGKILL or loss of the systemctl client must
    # not leave a later recovery believing the manager has no outstanding job.
    state['transaction']['restart_uncertain'] = True
    store.save(state)
    try:
        result = subprocess.run(['/bin/systemctl', 'restart', SERVICE], stdin=subprocess.DEVNULL,
                                timeout=RESTART_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise RestartUncertain('restart client failed or timed out; systemd job status uncertain; '
                               'pending transaction preserved') from error
    if not no_service_jobs():
        raise RestartUncertain('systemd job status uncertain; pending transaction preserved')
    state['transaction']['restart_uncertain'] = False
    store.save(state)
    try:
        return (result.returncode == 0 and health.healthy()
                and service_matches_current(current_revision()))
    except (DeploymentError, OSError, subprocess.SubprocessError):
        return False


def open_store(*, initialize=False):
    intake.trusted(ROOT, directory=True)
    if initialize:
        try:
            STATE.mkdir(mode=0o700)
        except FileExistsError:
            pass
    intake.trusted(STATE, directory=True)
    if stat.S_IMODE(STATE.stat().st_mode) != 0o700:
        raise DeploymentError('state directory must be root-only')
    store = transaction.StateStore(STATE)
    if os.path.lexists(store.path):
        intake.trusted(store.path)
        if store.path.stat().st_mode & 0o077:
            raise DeploymentError('state file must be root-only')
    return store


def initialize(revision):
    store = open_store(initialize=True)
    if os.path.lexists(store.path):
        raise DeploymentError('deployment state already initialized')
    if current_revision() != revision:
        raise DeploymentError('specified revision is not current')
    validate_release(revision, allow_legacy=True)
    if not no_service_jobs():
        raise RestartUncertain('systemd service job status uncertain; refusing initialization')
    if not health.healthy() or not service_matches_current(revision):
        raise DeploymentError('current release did not pass health checks')
    store.save({'current': revision, 'previous': None, 'transaction': None})
    print('INITIALIZE_OK')


def recover_if_needed(store):
    state = store.load()
    pending = state['transaction']
    if pending is None:
        if not no_service_jobs():
            raise RestartUncertain('systemd service job status uncertain; refusing to switch')
        if current_revision() != state['current']:
            raise DeploymentError('current does not match known healthy release')
        return False
    if pending.get('restart_uncertain', False):
        raise RestartUncertain('restart job status uncertain; pending transaction preserved; '
                               'manual systemd investigation required')
    if not no_service_jobs():
        raise RestartUncertain('systemd job status uncertain; pending transaction preserved')
    if current_revision() not in (pending['old'], pending['new']):
        raise DeploymentError('current does not match pending transaction')
    validate_release(pending['old'], allow_legacy=True)
    if transaction.recover(store, switch, restart_and_check):
        print('ROLLBACK_OK')
        return True
    return False


def deploy(revision):
    store = open_store()
    if recover_if_needed(store):
        raise DeploymentError('pending transaction was recovered; retry deployment')
    state = store.load()
    validate_release(state['current'], allow_legacy=True)
    validate_release(revision)
    if not health.healthy() or not service_matches_current(state['current']):
        raise DeploymentError('current release did not pass health checks')
    try:
        transaction.deploy(store, revision, switch, restart_and_check)
    except transaction.TransactionError as error:
        if str(error) == 'deployment failed; rollback succeeded':
            print('ROLLBACK_OK')
        raise DeploymentError(str(error)) from error
    print('DEPLOY_OK')


def recover_uncertain():
    """Admin-only recovery; caller holds lifecycle lock throughout."""
    store = open_store()
    state = store.load()
    pending = state['transaction']
    if pending is None or not pending.get('restart_uncertain', False):
        raise DeploymentError('no uncertain restart transaction')
    if current_revision() not in (pending['old'], pending['new']):
        raise DeploymentError('current does not match pending transaction')
    validate_release(pending['old'], allow_legacy=True)
    validate_release(pending['new'])
    cgroup = service_cgroup()
    try:
        result = subprocess.run(['/bin/systemctl', 'stop', SERVICE], stdin=subprocess.DEVNULL,
                                timeout=RESTART_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise RestartUncertain('unable to confirm service stop; pending transaction preserved') from error
    if result.returncode != 0 or not service_fully_stopped(cgroup):
        raise RestartUncertain('unable to confirm service stop; pending transaction preserved')
    # Clearing only the uncertainty flag is safe after the synchronous stop;
    # the pending transaction remains durable until rollback is healthy.
    pending['restart_uncertain'] = False
    store.save(state)
    if not recover_if_needed(store):
        raise DeploymentError('pending transaction disappeared during recovery')


def main():
    if os.geteuid() != 0 or len(sys.argv) not in (2, 3):
        print('ERROR: invalid invocation', file=sys.stderr)
        return 1
    action = sys.argv[1]
    lock = None
    try:
        if action not in ('initialize-existing', 'deploy', 'recover', 'recover-uncertain'):
            raise DeploymentError('invalid operation')
        if len(sys.argv) != (2 if action in ('recover', 'recover-uncertain') else 3):
            raise DeploymentError('invalid arguments')
        lock = intake.take_lock()
        if action == 'initialize-existing':
            initialize(sys.argv[2])
        elif action == 'deploy':
            deploy(sys.argv[2])
        elif action == 'recover':
            store = open_store()
            if not recover_if_needed(store):
                print('NO_RECOVERY_NEEDED')
        else:
            recover_uncertain()
    except (DeploymentError, RestartUncertain, transaction.TransactionError, intake.Rejected, OSError, ValueError,
            subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            os.close(lock)
    return 0


if __name__ == '__main__':
    sys.exit(main())
