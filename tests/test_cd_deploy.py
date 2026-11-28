import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import cd_deploy

REVISION = 'a' * 40
ENV = {
    'TRAVEL_DEPLOY_HOST': 'example.invalid',
    'TRAVEL_DEPLOY_USER': 'travel-deploy',
    'TRAVEL_DEPLOY_SSH_KEY': 'test-key',
    'TRAVEL_DEPLOY_KNOWN_HOSTS': 'test-known-host',
}


@pytest.fixture
def artifact(tmp_path):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        content = (REVISION + '\n').encode()
        entry = tarfile.TarInfo('REVISION')
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))
    path = tmp_path / 'artifact.tar.gz'
    path.write_bytes(output.getvalue())
    return path, hashlib.sha256(output.getvalue()).hexdigest()


def test_success_and_ssh_protocol(artifact, monkeypatch, capsys):
    path, digest = artifact

    def fake_run(args, **kwargs):
        assert args[-1] == f'deploy-artifact {REVISION} {digest}'
        assert args[-2] == 'travel-deploy@example.invalid'
        assert kwargs['input'] == path.read_bytes()
        assert 'StrictHostKeyChecking=yes' in args
        assert 'ForwardAgent=no' in args
        return subprocess.CompletedProcess(args, 0, b'RECEIVE_OK\nDEPLOY_OK\n', b'')

    monkeypatch.setattr(cd_deploy.subprocess, 'run', fake_run)
    cd_deploy.deploy(path, REVISION, digest, ENV)
    assert capsys.readouterr().out == 'DEPLOY_OK\n'


@pytest.mark.parametrize('returncode,output', [
    (1, b'DEPLOY_OK\n'), (0, b'RECEIVE_OK\n'), (0, b'ROLLBACK_OK\nDEPLOY_OK\n'),
    (1, b'ROLLBACK_OK\n'), (0, b'DEPLOY_OK\nDEPLOY_OK\n'),
])
def test_failed_deploy(artifact, monkeypatch, returncode, output):
    monkeypatch.setattr(cd_deploy.subprocess, 'run',
                        lambda *a, **k: subprocess.CompletedProcess(a, returncode, output, b''))
    with pytest.raises(ValueError):
        cd_deploy.deploy(artifact[0], REVISION, artifact[1], ENV)


def test_digest_revision_and_destination_rejected(artifact):
    with pytest.raises(ValueError, match='digest'):
        cd_deploy.deploy(artifact[0], REVISION, 'b' * 64, ENV)
    with pytest.raises(ValueError, match='revision mismatch'):
        cd_deploy.deploy(artifact[0], 'c' * 40, artifact[1], ENV)
    with pytest.raises(ValueError, match='destination'):
        cd_deploy.deploy(artifact[0], REVISION, artifact[1], {**ENV, 'TRAVEL_DEPLOY_HOST': '-oProxyCommand=x'})


def test_timeout_propagates(artifact, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('ssh', 1)

    monkeypatch.setattr(cd_deploy.subprocess, 'run', timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        cd_deploy.deploy(artifact[0], REVISION, artifact[1], ENV)


def test_workflow_gate_and_dependency():
    workflow = Path('.github/workflows/cd.yml').read_text(encoding='utf-8')
    gate = workflow.split('  build:', 1)[1].split('    runs-on:', 1)[0]
    deploy = workflow.split('  deploy:', 1)[1]
    for expected in ("vars.TRAVEL_CD_ENABLED == 'true'", "workflow_run.event == 'push'",
                     "workflow_run.head_branch == 'main'", "workflow_run.conclusion == 'success'",
                     "workflow_run.name == 'CI'", "workflow_run.path == '.github/workflows/ci.yml'",
                     'head_repository.id == github.event.repository.id'):
        assert expected in gate
    assert 'needs: build' in deploy
    assert 'environment: production' in deploy
    assert 'cancel-in-progress: false' in workflow
