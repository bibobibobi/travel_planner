#!/usr/bin/python3
"""Exercise the candidate entry with real extraction and a fake sudo endpoint."""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

repo = Path(sys.argv[1]).resolve(strict=True)
base = Path.home() / 'travel-deploy-test'
base.mkdir(exist_ok=True)
work = Path(tempfile.mkdtemp(prefix='entry-test-', dir=base))
incoming, staging, tools = (work / name for name in ('incoming', 'staging', 'tools'))
for directory in (incoming, staging, tools):
    directory.mkdir(mode=0o700)
for name in ('validate_artifact.py', 'extract_artifact.py'):
    shutil.copyfile(repo / 'scripts' / name, tools / name)
fake_sudo = work / 'sudo'
fake_sudo.write_text('''#!/usr/bin/python3
import hashlib, sys
args = sys.argv[1:]
if args == ['-n', '/usr/local/sbin/travel-deploy-control', 'status']:
    print('STATUS_FIXTURE')
elif args == ['-n', '/usr/local/sbin/travel-receive-wrapper']:
    rev, digest = sys.stdin.buffer.readline().decode('ascii').strip().split(' ')
    data = sys.stdin.buffer.read()
    assert len(rev) == 40 and hashlib.sha256(data).hexdigest() == digest
    print('RECEIVE_OK')
else:
    sys.exit(1)
''', encoding='utf-8')
fake_sudo.chmod(0o755)
candidate = (repo / 'deploy/server/travel-deploy-entry.candidate').read_text(encoding='utf-8')
for old, new in [('/opt/travel-app/incoming', str(incoming)),
                 ('/opt/travel-app/staging', str(staging)),
                 ('/opt/travel-app/tools', str(tools)), ('/usr/bin/sudo', str(fake_sudo))]:
    assert old in candidate
    candidate = candidate.replace(old, new)
entry = work / 'entry'
entry.write_text(candidate, encoding='utf-8')
entry.chmod(0o755)
revision = 'a' * 40
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
    for name, data in {'app.py': b'app', 'websocket_worker.py': b'worker',
                       'requirements.txt': b'flask', 'requirements-prod.txt': b'gunicorn',
                       'REVISION': (revision + '\n').encode(), 'dist/index.html': b'html',
                       'dist/app.js': b'js'}.items():
        member = tarfile.TarInfo(name)
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
artifact = buffer.getvalue()
digest = hashlib.sha256(artifact).hexdigest()


def invoke(command, data=b'', extra_env=None):
    env = os.environ.copy()
    env.update({'SSH_ORIGINAL_COMMAND': command})
    env.update(extra_env or {})
    return subprocess.run([str(entry)], input=data, capture_output=True, env=env, check=False)


assert invoke('ping').stdout == b'TRAVEL_DEPLOY_OK\n'
assert invoke('status').stdout == b'STATUS_FIXTURE\n'
upload = invoke(f'upload-artifact {revision} {digest}', artifact)
assert upload.returncode == 0
assert upload.stdout == f'UPLOAD_OK\nREVISION={revision}\nSHA256={digest}\nSIZE={len(artifact)}\n'.encode()
assert (incoming / 'artifact.tar.gz').read_bytes() == artifact
stage = invoke(f'stage-artifact {revision} {digest}', artifact)
assert stage.returncode == 0, stage.stderr
assert b'EXTRACTION_OK\n' in stage.stdout and stage.stdout.endswith(
    f'STAGE_OK\nREVISION={revision}\nSHA256={digest}\nSIZE={len(artifact)}\n'.encode())
assert (incoming / 'artifact.tar.gz').read_bytes() == artifact
deployed = invoke(f'deploy-artifact {revision} {digest}', artifact)
assert deployed.returncode == 0 and deployed.stdout == b'RECEIVE_OK\n'
for command in ('', 'ping extra', 'status extra', 'rollback ' + revision,
                'recover-uncertain', 'initialize-existing ' + revision,
                f'deploy-artifact {revision} {digest} extra',
                f'deploy-artifact {revision.upper()} {digest}',
                f'deploy-artifact {revision} {digest};id',
                f'upload-artifact {revision} {digest} extra'):
    bad = invoke(command)
    assert bad.returncode != 0 and bad.stderr == b'ERROR: Command not allowed\n', command
bad_hash = invoke(f'upload-artifact {revision} {"0" * 64}', artifact)
assert bad_hash.returncode != 0 and b'SHA256 mismatch' in bad_hash.stderr
marker = work / 'injected'
bash_env = work / 'bash-env'
bash_env.write_text(f'touch {marker}\n', encoding='utf-8')
injected = invoke('ping', extra_env={'PATH': str(work), 'BASH_ENV': str(bash_env),
                                     'PYTHONPATH': str(work), 'ENV': str(bash_env)})
assert injected.returncode == 0 and injected.stdout == b'TRAVEL_DEPLOY_OK\n' and not marker.exists()

# Exercise the unchanged status-only control wrapper against a fake systemctl.
systemctl = work / 'systemctl'
systemctl.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n', encoding='utf-8')
systemctl.chmod(0o755)
control_text = (repo / 'deploy/server/travel-deploy-control.candidate').read_text(encoding='utf-8')
control = work / 'control'
control.write_text(control_text.replace('/usr/bin/systemctl', str(systemctl)), encoding='utf-8')
control.chmod(0o755)
status = subprocess.run([str(control), 'status'], capture_output=True, check=False)
assert status.returncode == 0 and status.stdout == (
    b'show\ntravel.service\n-p\nActiveState\n-p\nSubState\n-p\nUser\n-p\nGroup\n')
for args, message in [([], b'ERROR: Invalid arguments\n'),
                      (['status', 'extra'], b'ERROR: Invalid arguments\n'),
                      (['rollback'], b'ERROR: Operation not allowed\n')]:
    result = subprocess.run([str(control), *args], capture_output=True, check=False)
    assert result.returncode != 0 and result.stderr == message

# The sudo entry must reject every argument before running Python.
wrapper = repo / 'deploy/server/receive-wrapper'
for args in (['x'], ['--'], ['status', 'extra']):
    result = subprocess.run(['/bin/bash', str(wrapper), *args], capture_output=True, check=False)
    assert result.returncode != 0 and result.stderr == b'ERROR: Invalid arguments\n'
fake_python = work / 'python'
fake_python.write_text('#!/bin/bash -p\nprintf "%s\\n" "$@"\n', encoding='utf-8')
fake_python.chmod(0o755)
test_wrapper = work / 'receive-wrapper'
test_wrapper.write_text(wrapper.read_text(encoding='utf-8').replace('/usr/bin/python3', str(fake_python)),
                        encoding='utf-8')
test_wrapper.chmod(0o755)
environment = os.environ.copy()
environment.update({'BASH_ENV': str(bash_env), 'PATH': str(work), 'PYTHONPATH': str(work)})
result = subprocess.run([str(test_wrapper)], env=environment, capture_output=True, check=False)
assert result.returncode == 0 and result.stdout == (
    b'-E\n-s\n-B\n/usr/local/lib/travel-deploy/deploy_pipeline.py\n')
assert not marker.exists()
rules = [line.strip() for line in (repo / 'deploy/server/sudoers.candidate').read_text(
    encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')]
assert rules == [
    'travel-deploy ALL=(root) NOPASSWD: NOSETENV: /usr/local/sbin/travel-deploy-control status',
    'travel-deploy ALL=(root) NOPASSWD: NOSETENV: /usr/local/sbin/travel-receive-wrapper ""',
]
print('ENTRY_COMPATIBILITY_OK')
print('Test directory retained:', work)
