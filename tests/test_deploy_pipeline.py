import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('fcntl')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy' / 'server'))
import deploy_pipeline as pipeline

REVISION, DIGEST, OLD = 'a' * 40, 'b' * 64, 'c' * 40


@pytest.fixture
def setup_pipeline(tmp_path, monkeypatch):
    releases = tmp_path / 'releases'
    releases.mkdir()
    lock = tmp_path / 'lock'
    lock.touch()
    lock_fd = os.open(lock, os.O_RDONLY)
    events = []
    monkeypatch.setattr(pipeline.receiver, 'take_lock', lambda: lock_fd)
    monkeypatch.setattr(pipeline.controller, 'RELEASES', releases)
    monkeypatch.setattr(pipeline.controller, 'open_store', lambda: SimpleNamespace(load=lambda: {'current': OLD}))
    monkeypatch.setattr(pipeline.controller, 'recover_if_needed', lambda store: False)
    def receive(fd, *, lifecycle_fd, allow_existing):
        events.append(('receive', fd, lifecycle_fd, allow_existing))
        return REVISION, DIGEST
    def build(revision, digest, *, lifecycle_fd):
        events.append(('build', revision, digest, lifecycle_fd))
        return revision, digest
    monkeypatch.setattr(pipeline.receiver, 'accept', receive)
    monkeypatch.setattr(pipeline.builder, 'build', build)
    monkeypatch.setattr(pipeline.controller, 'validate_release', lambda revision: DIGEST)
    monkeypatch.setattr(pipeline.controller, 'deploy', lambda revision: events.append(('deploy', revision)))
    return releases, lock_fd, events


def test_pipeline_shares_one_lock_and_orders_stages(setup_pipeline):
    _, lock_fd, events = setup_pipeline
    pipeline.run(9)
    assert events == [('receive', 9, lock_fd, True), ('build', REVISION, DIGEST, lock_fd), ('deploy', REVISION)]
    with pytest.raises(OSError):
        os.fstat(lock_fd)


def test_mismatched_builder_result_never_deploys(setup_pipeline, monkeypatch):
    _, _, events = setup_pipeline
    monkeypatch.setattr(pipeline.builder, 'build', lambda *args, **kwargs: (REVISION, '0' * 64))
    with pytest.raises(pipeline.PipelineError, match='builder result'):
        pipeline.run(9)
    assert not any(event[0] == 'deploy' for event in events)


def test_existing_release_digest_mismatch_never_deploys(setup_pipeline, monkeypatch):
    releases, _, events = setup_pipeline
    (releases / REVISION).mkdir()
    monkeypatch.setattr(pipeline.controller, 'validate_release', lambda revision: '0' * 64)
    with pytest.raises(pipeline.PipelineError, match='digest mismatch'):
        pipeline.run(9)
    assert not any(event[0] in ('build', 'deploy') for event in events)


def test_receive_failure_never_builds_or_deploys(setup_pipeline, monkeypatch):
    _, _, events = setup_pipeline
    def fail(*args, **kwargs):
        raise pipeline.receiver.Rejected('invalid artifact')
    monkeypatch.setattr(pipeline.receiver, 'accept', fail)
    with pytest.raises(pipeline.receiver.Rejected):
        pipeline.run(9)
    assert not events


def test_builder_failure_never_deploys(setup_pipeline, monkeypatch):
    _, _, events = setup_pipeline
    def fail(*args, **kwargs):
        raise pipeline.builder.BuildError('build failed')
    monkeypatch.setattr(pipeline.builder, 'build', fail)
    with pytest.raises(pipeline.builder.BuildError):
        pipeline.run(9)
    assert not any(event[0] == 'deploy' for event in events)
