#!/usr/bin/python3
"""Exercise only real transient services, without building a venv or downloading packages."""
import os
import pwd
import sys
import time
import uuid
from pathlib import Path

import release_builder as builder

mount, build_user, prefix = sys.argv[1:]
mount = Path(mount)
assert os.geteuid() == 0 and mount.parent == Path('/run')
assert mount.name.startswith('travel-release-test.') and mount.is_dir()
root = mount / 'app'
root.mkdir(mode=0o755)
for name in ('releases', 'build-work', 'shared'):
    (root / name).mkdir(mode=0o755)
os.chmod(root / 'build-work', 0o711)
os.chmod(root / 'shared', 0o750)
account = pwd.getpwnam(build_user)
stage = root / 'build-work/cgroup-test'
stage.mkdir(mode=0o700)
os.chown(stage, account.pw_uid, account.pw_gid)
builder.ROOT = root
builder.RELEASES = root / 'releases'
builder.WORK = root / 'build-work'
builder.SHARED = root / 'shared'
builder.BUILDER = build_user
builder.FREE_BYTES = 200 * 1024 * 1024
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
print('CGROUP_INTEGRATION_OK')
