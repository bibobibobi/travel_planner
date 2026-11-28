#!/usr/bin/python3
"""Test real systemd and filesystem behavior under a disposable bind mount."""
import hashlib
import io
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path

import receive_artifact as intake
import release_builder as builder
import release_tree

mount, build_user, app_user, deploy_user, prefix = sys.argv[1:]
mount = Path(mount)
assert os.geteuid() == 0 and mount.parent == Path('/run')
assert mount.name.startswith('travel-release-test.') and mount.is_dir()
root = mount / 'app'
root.mkdir(mode=0o755)
for name in ('releases', 'build-work', 'artifact-snapshots', 'shared'):
    (root / name).mkdir(mode=0o755)
os.chmod(root / 'build-work', 0o711)
build_account = pwd.getpwnam(build_user)
app_account = pwd.getpwnam(app_user)
os.chown(root / 'artifact-snapshots', 0, build_account.pw_gid)
os.chmod(root / 'artifact-snapshots', 0o710)
os.chown(root / 'shared', 0, app_account.pw_gid)
os.chmod(root / 'shared', 0o750)
(root / 'shared' / '.env').write_text('TEST_SECRET=only-test-data\n', encoding='ascii')
os.chown(root / 'shared' / '.env', 0, app_account.pw_gid)
os.chmod(root / 'shared' / '.env', 0o640)
(root / 'shared' / 'uploads').mkdir(mode=0o750)
os.chown(root / 'shared' / 'uploads', app_account.pw_uid, app_account.pw_gid)
lock = root / '.lifecycle.lock'
lock.touch(mode=0o644)

builder.ROOT = intake.ROOT = root
builder.RELEASES = root / 'releases'
builder.WORK = root / 'build-work'
builder.SHARED = root / 'shared'
builder.SNAPSHOTS = root / 'artifact-snapshots'
builder.EXTRACTOR = mount / 'tools/extract_artifact.py'
builder.WORKER = mount / 'tools/release_build_worker.py'
builder.BUILDER = build_user
builder.UNIT_PREFIX = prefix
builder.FREE_BYTES = 200 * 1024 * 1024
intake.LOCK = lock

old_rev = 'b' * 40
old = root / 'releases' / old_rev
old.mkdir()
(old / 'sentinel').write_text('unchanged', encoding='ascii')
(root / 'current').symlink_to(Path('releases') / old_rev)


def make_artifact(revision, requirements):
    data = io.BytesIO()
    files = {'app.py': b'app', 'websocket_worker.py': b'worker',
             'requirements.txt': b'gunicorn==23.0.0\n', 'requirements-prod.txt': requirements,
             'REVISION': (revision + '\n').encode(), 'dist/index.html': b'html',
             'dist/app.js': b'js'}
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    content = data.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    snapshot = root / 'artifact-snapshots' / f'{revision}-{digest}.tar.gz'
    snapshot.write_bytes(content)
    os.chown(snapshot, 0, build_account.pw_gid)
    os.chmod(snapshot, 0o440)
    return digest


def as_user(user, *command, cwd=None):
    return subprocess.run(
        ['/usr/sbin/runuser', '-u', user, '--', *map(str, command)],
        check=False,
        capture_output=True,
        timeout=60,
        cwd=cwd if cwd is not None else "/",
    )


def expect_failure(function, expected):
    try:
        function()
    except builder.BuildError as error:
        assert expected in str(error), (expected, str(error))
    else:
        raise AssertionError('expected build failure: ' + expected)


def current_unchanged():
    assert os.readlink(root / 'current') == 'releases/' + old_rev
    assert (old / 'sentinel').read_text(encoding='ascii') == 'unchanged'


assert as_user(build_user, '/usr/bin/test', '-r', root / 'shared/.env').returncode != 0
read_secret = as_user(build_user, '/usr/bin/python3', '-c',
                      "import sys; open(sys.argv[1], encoding='utf-8').read()", root / 'shared/.env')
assert read_secret.returncode != 0
for user in (build_user, deploy_user):
    assert as_user(user, '/usr/bin/cat', root / 'shared/.env').returncode != 0
    assert as_user(user, '/usr/bin/ls', root / 'shared/uploads').returncode != 0
    assert as_user(user, '/usr/bin/touch', root / 'shared/uploads/forbidden').returncode != 0
assert as_user(app_user, '/usr/bin/cat', root / 'shared/.env').stdout == b'TEST_SECRET=only-test-data\n'
upload = root / 'shared/uploads/app-test'
write_upload = as_user(app_user, '/usr/bin/python3', '-c',
                       "import sys; open(sys.argv[1], 'wb').write(b'upload-test')", upload)
assert write_upload.returncode == 0
assert as_user(app_user, '/usr/bin/cat', upload).stdout == b'upload-test'
assert as_user(app_user, '/usr/bin/rm', upload).returncode == 0
revision = 'a' * 40
digest = make_artifact(revision, b'gunicorn==23.0.0\n')
builder.build(revision, digest)
release = root / 'releases' / revision
current_unchanged()
assert release.is_dir() and os.readlink(release / '.env') == str(root / 'shared/.env')
completion = release / '.release-ready'
assert completion.read_text(encoding='ascii') == f'REVISION={revision}\nSHA256={digest}\n'
assert completion.stat().st_uid == 0 and stat.S_IMODE(completion.stat().st_mode) == 0o444
builder.check_capacity(builder.WORK)
for user in (app_user, build_user, deploy_user):
    assert as_user(user, '/usr/bin/test', '-w', completion).returncode != 0
assert os.readlink(release / 'uploads') == str(root / 'shared/uploads')
venv = release / 'venv'
for executable in ('python', 'pip', 'gunicorn'):
    result = as_user(
        app_user,
        release / 'venv/bin' / executable,
        '--version',
        cwd=release,
    )
    assert result.returncode == 0, (executable, result.stderr)
identity = as_user(app_user, venv / 'bin/python', '-c',
                   'import json,sys; print(json.dumps([sys.prefix, sys.executable]))')
assert identity.returncode == 0, identity.stderr
venv_prefix, executable = json.loads(identity.stdout)
assert Path(os.path.abspath(venv_prefix)) == venv
executable_path = Path(os.path.abspath(executable))
assert executable_path.parent == venv / 'bin'
assert re.fullmatch(r'python(?:3(?:\.[0-9]+)?)?', executable_path.name)

pip_version = as_user(app_user, venv / 'bin/pip', '--version')
assert pip_version.returncode == 0, pip_version.stderr
pip_output = pip_version.stdout.decode('utf-8').strip()
match = re.fullmatch(r'pip \S+ from (.+) \(python [^)]+\)', pip_output)
assert match, pip_output
pip_location = Path(match.group(1)).resolve(strict=True)
assert pip_location.name == 'pip' and pip_location.is_relative_to(venv.resolve(strict=True)), pip_output

# Console entry points may be direct shebangs or distlib's shell wrappers.
# Inspect the launcher, not arbitrary package data, and require its interpreter
# to be under this exact final venv rather than an old build/temporary path.
python_path = re.compile(re.escape(os.fsencode(venv / 'bin/python')) +
                         rb'(?:3(?:\.[0-9]+)?)?(?=[\s"\'\\]|$)')
for name in ('pip', 'gunicorn'):
    launcher = (venv / 'bin' / name).read_bytes()
    header = b'\n'.join(launcher.splitlines()[:4])
    assert python_path.search(header), (name, header)
    assert os.fsencode(root / 'build-work') not in launcher, name
    assert os.fsencode(root / 'releases' / '.release-') not in launcher, name
for user in (build_user, app_user, deploy_user):
    for path in (release / 'app.py', release / 'venv/bin/pip'):
        assert as_user(user, '/usr/bin/test', '-w', path).returncode != 0
        attempt = as_user(user, '/usr/bin/python3', '-c',
                          "import sys; open(sys.argv[1], 'ab').write(b'alter')", path)
        assert attempt.returncode != 0, (user, path)
assert as_user(app_user, '/usr/bin/test', '-r', release / 'app.py').returncode == 0
assert stat.S_IMODE((release / 'venv/bin/pip').stat().st_mode) == 0o555
inventory = release / 'venv/BUILD-PACKAGES.txt'
assert inventory.stat().st_uid == 0 and stat.S_IMODE(inventory.stat().st_mode) == 0o444
assert 'gunicorn==23.0.0' in inventory.read_text(encoding='utf-8').lower()
expect_failure(lambda: builder.build(revision, digest), 'already exists')
assert (release / 'app.py').read_bytes() == b'app'

bad_rev = 'c' * 40
bad_digest = make_artifact(bad_rev, b'not a valid requirement !!!\n')
expect_failure(lambda: builder.build(bad_rev, bad_digest), 'build worker failed')
assert not (root / 'releases' / bad_rev).exists()
assert not list((root / 'build-work').iterdir())
current_unchanged()

limited_rev = 'd' * 40
limited_digest = make_artifact(limited_rev, b'gunicorn==23.0.0\n')
old_free = builder.FREE_BYTES
builder.FREE_BYTES = 10**18
try:
    expect_failure(lambda: builder.build(limited_rev, limited_digest), 'insufficient disk')
finally:
    builder.FREE_BYTES = old_free
assert not (root / 'releases' / limited_rev).exists()
current_unchanged()
old_limit = builder.RELEASE_BYTES
builder.RELEASE_BYTES = 0
try:
    expect_failure(lambda: builder.build(limited_rev, limited_digest), 'releases capacity exceeded')
finally:
    builder.RELEASE_BYTES = old_limit
assert not (root / 'releases' / limited_rev).exists()
current_unchanged()

# Run a real cgroup whose child detaches into a new session. It must die when
# the unit ends, before it can write its delayed marker.
stage = root / 'build-work' / 'cgroup-test'
stage.mkdir(mode=0o700)
os.chown(stage, build_account.pw_uid, build_account.pw_gid)
marker = stage / 'escaped'
source = mount / 'tools/spawn_background.py'
source.write_text("import os,time\nif os.fork()==0:\n os.setsid(); time.sleep(4); "
                  f"open({str(marker)!r},'w').write('escaped')\n", encoding='ascii')
builder.service_command(prefix + '-child-' + uuid.uuid4().hex, stage, ['/usr/bin/python3', source], timeout=15)
time.sleep(5)
assert not marker.exists(), 'background process survived the build unit'
try:
    builder.service_command(prefix + '-timeout-' + uuid.uuid4().hex, stage,
                            ['/usr/bin/python3', '-c', 'import time; time.sleep(30)'], timeout=2)
except builder.QuiescentFailure as error:
    assert 'build worker failed' in str(error) or 'build timed out' in str(error)
else:
    raise AssertionError('timed-out unit unexpectedly succeeded')

# Real special-file and link checks on the root-owned destination boundary.
for kind in ('symlink', 'hardlink', 'fifo'):
    source_dir = root / 'build-work' / ('source-' + kind)
    target_dir = root / 'build-work' / ('target-' + kind)
    source_dir.mkdir()
    target_dir.mkdir()
    item = source_dir / 'bad'
    if kind == 'symlink':
        item.symlink_to('/etc/passwd')
    elif kind == 'fifo':
        os.mkfifo(item)
    else:
        (source_dir / 'original').write_bytes(b'x')
        os.link(source_dir / 'original', item)
    try:
        builder.copy_output(source_dir, target_dir)
    except release_tree.UnsafeTree:
        pass
    else:
        raise AssertionError('accepted ' + kind)

current_unchanged()
print('RELEASE_INTEGRATION_OK')
