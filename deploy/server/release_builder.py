#!/usr/bin/python3
"""Build a release from a module-1 snapshot; never switch or start services."""
import ctypes
import errno
import os
import pwd
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import receive_artifact as intake
import release_tree

ROOT = Path('/opt/travel-app')
RELEASES = ROOT / 'releases'
WORK = ROOT / 'build-work'
SHARED = ROOT / 'shared'
SNAPSHOTS = ROOT / 'artifact-snapshots'
EXTRACTOR = ROOT / 'tools/extract_artifact.py'
WORKER = Path('/usr/local/lib/travel-deploy/release_build_worker.py')
BUILDER = 'travel-build'
UNIT_PREFIX = 'travel-build'
BUILD_BYTES = 600 * 1024 * 1024
RELEASE_BYTES = 3 * 1024 * 1024 * 1024
FREE_BYTES = 700 * 1024 * 1024


class BuildError(RuntimeError):
    pass


class QuiescentFailure(BuildError):
    """The build failed after its cgroup was confirmed empty."""


def disk_bytes(path):
    """Measure disk usage with bounded retries for transient file removal."""
    command = ['/usr/bin/du', '-sx', '-B1', '--', str(path)]

    for attempt in range(3):
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, 'LC_ALL': 'C'},
        )

        if proc.returncode == 0:
            return int(proc.stdout.split(None, 1)[0])

        errors = [
            line for line in proc.stderr.splitlines()
            if line.strip()
        ]

        transient = bool(errors) and all(
            'cannot access' in line
            and line.endswith('No such file or directory')
            for line in errors
        )

        if transient and path.exists() and attempt < 2:
            print(
                f'[capacity] transient scan failure; '
                f'retry {attempt + 1}/2: {path}',
                file=sys.stderr,
                flush=True,
            )
            time.sleep(0.2)
            continue

        raise BuildError(
            f'disk usage check failed for {path}: '
            f'{proc.stderr.strip() or proc.returncode}'
        )

    raise BuildError(f'disk usage check failed for {path}')


def check_capacity(*paths, copy_reserve=0):
    if shutil.disk_usage(ROOT).free < FREE_BYTES + copy_reserve:
        raise BuildError('insufficient disk space')
    if disk_bytes(RELEASES) > RELEASE_BYTES:
        raise BuildError('releases capacity exceeded')
    roots = []
    for path in sorted((Path(os.path.abspath(path)) for path in paths if path.exists()),
                       key=lambda item: len(item.parts)):
        if not any(path == parent or parent in path.parents for parent in roots):
            roots.append(path)
    if sum(disk_bytes(path) for path in roots) > BUILD_BYTES:
        raise BuildError('build capacity exceeded')


def unit_state(unit):
    result = subprocess.run(['/usr/bin/systemctl', 'show', unit, '--all', '--no-pager',
                             '-p', 'LoadState', '-p', 'ActiveState', '-p', 'SubState',
                             '-p', 'ControlGroup', '-p', 'Job'],
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        listing = subprocess.run(['/usr/bin/systemctl', 'list-units', '--all', '--no-legend',
                                  '--plain', '--no-pager', unit + '.service'], capture_output=True,
                                 text=True, timeout=10, check=False)
        if listing.returncode or any(unit + '.service' in line.split() for line in listing.stdout.splitlines()):
            raise BuildError('cannot inspect systemd unit')
        # The manager is reachable and the exact unit is unloaded. The caller
        # must still check pending jobs and the previously observed cgroup.
        return {'LoadState': 'not-found', 'ActiveState': 'inactive', 'SubState': 'dead',
                'ControlGroup': '', 'Job': ''}
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if not {'LoadState', 'ActiveState', 'SubState', 'ControlGroup', 'Job'} <= values.keys():
        raise BuildError('incomplete systemd unit state')
    return values


def has_pending_job(unit):
    result = subprocess.run(['/usr/bin/systemctl', 'list-jobs', '--no-legend', '--plain', '--no-pager'],
                            capture_output=True, text=True, timeout=10, check=True)
    return any(unit + '.service' in line.split() or unit in line.split()
               for line in result.stdout.splitlines())


def ensure_unit_available(unit):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,180}', unit):
        raise BuildError('invalid transient service name')
    result = subprocess.run(['/usr/bin/systemctl', 'list-units', '--all', '--no-legend',
                             '--plain', '--no-pager', unit + '.service'],
                            capture_output=True, text=True, timeout=10, check=True)
    if (any(unit + '.service' in line.split() for line in result.stdout.splitlines()) or
            has_pending_job(unit) or
            (Path('/sys/fs/cgroup/system.slice') / (unit + '.service')).exists()):
        raise BuildError('transient service name is already in use')


def diagnostic(unit, phase, **fields):
    details = ' '.join(f'{key}={shlex.quote(str(value))}' for key, value in fields.items())
    print(f'[release-builder] unit={unit} phase={phase} {details}', file=sys.stderr, flush=True)


def service_command(unit, writable, command, timeout=600):
    """Run one systemd service and require its cgroup to be empty afterwards."""
    ensure_unit_available(unit)
    options = [
        '--wait', '--quiet', '--slice=system.slice', '--unit', unit, '--property=Type=exec',
        f'--property=User={BUILDER}', '--property=NoNewPrivileges=yes',
        '--property=ProtectSystem=strict', '--property=ProtectHome=yes',
        '--property=PrivateTmp=yes', '--property=PrivateDevices=yes',
        '--property=ProtectControlGroups=yes', '--property=ProtectKernelTunables=yes',
        '--property=ProtectKernelModules=yes', '--property=RestrictNamespaces=yes',
        '--property=RestrictSUIDSGID=yes', '--property=KillMode=control-group',
        '--property=SendSIGKILL=yes', '--property=TimeoutStopSec=15s',
        '--property=MemoryMax=350M', '--property=MemorySwapMax=512M',
        '--property=TasksMax=64', '--property=CPUQuota=50%',
        '--property=LimitFSIZE=209715200', f'--property=RuntimeMaxSec={timeout}s',
        f'--property=InaccessiblePaths={SHARED} -/run/dbus/system_bus_socket -/run/systemd/private',
        f'--property=ReadWritePaths={writable}',
        '--property=TemporaryFileSystem=/tmp:rw,nosuid,nodev,size=64M',
        '--setenv=PATH=/usr/bin:/bin', '--setenv=HOME=/nonexistent',
        '--setenv=PYTHONDONTWRITEBYTECODE=1',
    ]
    gate = WORK / ('.gate-' + uuid.uuid4().hex)
    diagnostic(unit, 'start', systemd_run_options=shlex.join(options), gate=gate,
               executable=command[0], argument_count=len(command) - 1)
    process = subprocess.Popen(['/usr/bin/systemd-run', *options, '--', '/usr/bin/env', '-i',
                                'PATH=/usr/bin:/bin', 'HOME=/nonexistent', 'LANG=C.UTF-8',
                                '/bin/sh', '-c',
                                'while [ ! -r "$1" ]; do /bin/sleep 0.05; done; shift; exec "$@"',
                                'release-gate', str(gate), *map(str, command)],
                               stdin=subprocess.DEVNULL)
    failure = None
    deadline = time.monotonic() + timeout + 20
    cgroup = None
    try:
        # The unprivileged gate holds the main process alive until root has
        # observed the actual ControlGroup, including for very fast commands.
        startup_deadline = time.monotonic() + min(timeout, 30)
        while cgroup is None:
            if process.poll() is not None or time.monotonic() >= startup_deadline:
                raise BuildError('unable to observe build cgroup during startup')
            try:
                state = unit_state(unit)
            except BuildError:
                time.sleep(0.05)
                continue
            actual = state['ControlGroup']
            if actual:
                expected = '/system.slice/' + unit + '.service'
                if actual != expected or state['LoadState'] != 'loaded':
                    raise BuildError('unexpected build cgroup')
                diagnostic(unit, 'observed', load=state['LoadState'], active=state['ActiveState'],
                           sub=state['SubState'], cgroup=actual, job=state['Job'])
                cgroup = Path('/sys/fs/cgroup') / actual.lstrip('/')
                fd = os.open(gate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
                os.fchmod(fd, 0o644)
                os.close(fd)
                break
            time.sleep(0.05)
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise BuildError('build timed out')
            check_capacity(WORK, writable)
            time.sleep(1)
        if process.returncode:
            raise BuildError(f'build worker failed (systemd-run exit {process.returncode})')
    except (BuildError, OSError, ValueError, subprocess.SubprocessError) as error:
        failure = error
    finally:
        diagnostic(unit, 'stopping', client_exit=process.poll(), cgroup=cgroup or 'unobserved',
                   failure=failure or 'none')
        try:
            state = unit_state(unit)
            diagnostic(unit, 'before-stop', load=state['LoadState'], active=state['ActiveState'],
                       sub=state['SubState'], cgroup=state['ControlGroup'] or 'none',
                       job=state['Job'], pending=has_pending_job(unit))
        except (BuildError, OSError, subprocess.SubprocessError) as error:
            diagnostic(unit, 'before-stop-unavailable', error_type=type(error).__name__)
        # With no observed cgroup, a pending start cannot be ruled out.
        try:
            subprocess.run(['/usr/bin/systemctl', 'stop', unit], timeout=30, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            try:
                gate.unlink(missing_ok=True)
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        deadline = time.monotonic() + 15
        try:
            verified = False
            last_report = None
            while cgroup is not None and time.monotonic() < deadline:
                state = unit_state(unit)
                current = state['ControlGroup']
                if current and current != '/system.slice/' + unit + '.service':
                    raise BuildError('systemd cgroup changed')
                empty = not cgroup.exists()
                if not empty:
                    try:
                        events = dict(line.split() for line in (cgroup / 'cgroup.events').read_text(
                            encoding='ascii').splitlines())
                        empty = events.get('populated') == '0'
                    except FileNotFoundError:
                        empty = not cgroup.exists()
                pending = has_pending_job(unit)
                report = (state['LoadState'], state['ActiveState'], state['SubState'], current,
                          state['Job'], pending, empty)
                if report != last_report:
                    diagnostic(unit, 'verify-stop', load=state['LoadState'], active=state['ActiveState'],
                               sub=state['SubState'], cgroup=current or 'unloaded', job=state['Job'],
                               pending=pending, cgroup_empty=empty)
                    last_report = report
                idle = (state['LoadState'] in ('loaded', 'not-found') and
                        state['ActiveState'] in ('inactive', 'failed') and
                        state['SubState'] in ('dead', 'failed', 'exited') and
                        state['Job'] in ('', '0') and not pending)
                if empty and idle:
                    diagnostic(unit, 'stopped', load=state['LoadState'], active=state['ActiveState'],
                               sub=state['SubState'], cgroup=current or 'unloaded',
                               observed_cgroup=cgroup, job=state['Job'], client_exit=process.returncode)
                    verified = True
                    break
                time.sleep(0.1)
            if not verified:
                raise BuildError(f'unable to verify empty build cgroup; preserve build files '
                                 f'(systemd-run exit {process.returncode}; initial error: {failure})') from failure
        finally:
            gate.unlink(missing_ok=True)
    if failure is not None:
        raise QuiescentFailure(str(failure)) from failure


def rename_noreplace(source, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    call = libc.renameat2
    call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    call.restype = ctypes.c_int
    if call(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise BuildError('release already exists')
        raise OSError(code, os.strerror(code))


def copy_output(source, destination):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    src = os.open(source, flags)
    dst = os.open(destination, flags)
    try:
        release_tree.copy_tree(src, dst, max_bytes=BUILD_BYTES)
    finally:
        os.close(src)
        os.close(dst)


def ensure_builder_idle(uid):
    for path in Path('/proc').iterdir():
        if path.name.isdecimal():
            try:
                if path.stat().st_uid == uid:
                    raise BuildError('build account already has a running process')
            except FileNotFoundError:
                continue


def build(revision, digest, *, lifecycle_fd=None):
    if not intake.REVISION.fullmatch(revision) or not intake.DIGEST.fullmatch(digest):
        raise BuildError('invalid revision or digest')
    if not shutil.rmtree.avoids_symlink_attacks:
        raise BuildError('safe recursive cleanup is unavailable')
    for path in (ROOT, RELEASES, WORK, SNAPSHOTS, SHARED):
        intake.trusted(path, directory=True)
    for path in (EXTRACTOR, EXTRACTOR.parent / 'validate_artifact.py', WORKER):
        intake.trusted(path)
    account = pwd.getpwnam(BUILDER)
    shared = SHARED.stat()
    groups = os.getgrouplist(BUILDER, account.pw_gid)
    if (account.pw_uid == 0 or account.pw_shell not in ('/usr/sbin/nologin', '/bin/false')
            or account.pw_uid == shared.st_uid or shared.st_gid in groups
            or shared.st_mode & 0o007):
        raise BuildError('builder can access shared data')
    snapshot = SNAPSHOTS / f'{revision}-{digest}.tar.gz'
    intake.trusted(snapshot)
    if snapshot.stat().st_mode & 0o022:
        raise BuildError('snapshot is writable')
    lock = intake.take_lock() if lifecycle_fd is None else lifecycle_fd
    if lifecycle_fd is not None:
        intake.reuse_lock(lock)
    work = None
    provisional = RELEASES / revision
    published = False
    owns_provisional = False
    safe_to_remove = True
    try:
        ensure_builder_idle(account.pw_uid)
        if os.path.lexists(provisional):
            raise BuildError('release already exists')
        if (ROOT / 'current').is_symlink() and os.path.realpath(ROOT / 'current') == str(provisional):
            raise BuildError('current points to requested release')
        check_capacity(WORK)
        work = Path(tempfile.mkdtemp(prefix='.build-', dir=WORK))
        os.chmod(work, 0o711)
        stage = work / 'stage'
        stage.mkdir(mode=0o700)
        os.chown(stage, account.pw_uid, account.pw_gid)
        token = uuid.uuid4().hex
        safe_to_remove = False
        try:
            service_command(UNIT_PREFIX + '-extract-' + token, stage,
                            ['/usr/bin/python3', '-E', '-s', '-B', EXTRACTOR, '--artifact', snapshot,
                             '--revision', revision, '--sha256', digest, '--staging-dir', stage], 120)
        except QuiescentFailure:
            safe_to_remove = True
            raise
        safe_to_remove = True
        check_capacity(work, copy_reserve=disk_bytes(stage / revision))
        temporary = Path(tempfile.mkdtemp(prefix='.release-', dir=RELEASES))
        try:
            copy_output(stage / revision, temporary)
            os.chmod(temporary, 0o755)
            rename_noreplace(temporary, provisional)
            owns_provisional = True
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        venv = provisional / 'venv'
        venv.mkdir(mode=0o700)
        os.chown(venv, account.pw_uid, account.pw_gid)
        safe_to_remove = False
        try:
            service_command(UNIT_PREFIX + '-install-' + token, venv,
                            ['/usr/bin/python3', '-E', '-s', '-B', WORKER, provisional])
        except QuiescentFailure:
            safe_to_remove = True
            raise
        safe_to_remove = True
        check_capacity(work, venv, copy_reserve=disk_bytes(provisional))
        frozen = Path(tempfile.mkdtemp(prefix='.release-', dir=RELEASES))
        try:
            copy_output(provisional, frozen)
            check_capacity(work, venv)
            os.symlink(str(SHARED / '.env'), frozen / '.env')
            os.symlink(str(SHARED / 'uploads'), frozen / 'uploads')
            os.chmod(frozen, 0o755)
            # No current link can refer to this newly reserved revision.
            abandoned = work / 'unfrozen-release'
            os.rename(provisional, abandoned)
            owns_provisional = False
            rename_noreplace(frozen, provisional)
            owns_provisional = True
        finally:
            if frozen.exists():
                shutil.rmtree(frozen)
        # Verify the copied, immutable venv at its final path, without root.
        safe_to_remove = False
        try:
            service_command(UNIT_PREFIX + '-verify-' + token, stage,
                            ['/usr/bin/python3', '-E', '-s', '-B', WORKER, '--verify', provisional], 120)
        except QuiescentFailure:
            safe_to_remove = True
            raise
        safe_to_remove = True
        check_capacity(work, provisional / 'venv')
        marker = provisional / '.release-ready'
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o444)
            payload = f'REVISION={revision}\nSHA256={digest}\n'.encode('ascii')
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(provisional, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        check_capacity(work, provisional / 'venv')
        published = True
    finally:
        if safe_to_remove:
            if owns_provisional and not published and provisional.exists():
                shutil.rmtree(provisional)
            if work is not None:
                shutil.rmtree(work)
        if lifecycle_fd is None:
            os.close(lock)
    print(f'RELEASE_READY\nREVISION={revision}\nSHA256={digest}')
    return revision, digest


def main():
    if os.geteuid() != 0 or len(sys.argv) != 3:
        print('ERROR: invalid invocation', file=sys.stderr)
        return 1
    try:
        build(sys.argv[1], sys.argv[2])
    except (OSError, ValueError, BuildError, intake.Rejected, release_tree.UnsafeTree,
            subprocess.SubprocessError) as error:
        print(f'ERROR: release build failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
