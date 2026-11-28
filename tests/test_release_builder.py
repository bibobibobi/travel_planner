import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('fcntl')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy' / 'server'))
import release_builder as builder


def test_duplicate_release_is_not_removed(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    for name in ('releases', 'build-work', 'shared', 'artifact-snapshots', 'tools'):
        (root / name).mkdir(parents=True, exist_ok=True)
    rev, digest = 'a' * 40, 'b' * 64
    existing = root / 'releases' / rev
    existing.mkdir()
    (existing / 'sentinel').write_text('preserve', encoding='ascii')
    (root / 'artifact-snapshots' / f'{rev}-{digest}.tar.gz').write_bytes(b'snapshot')
    lock = root / 'lock'
    lock.touch()
    monkeypatch.setattr(builder, 'ROOT', root)
    monkeypatch.setattr(builder, 'RELEASES', root / 'releases')
    monkeypatch.setattr(builder, 'WORK', root / 'build-work')
    monkeypatch.setattr(builder, 'SHARED', root / 'shared')
    monkeypatch.setattr(builder, 'SNAPSHOTS', root / 'artifact-snapshots')
    monkeypatch.setattr(builder, 'EXTRACTOR', root / 'tools/extract_artifact.py')
    monkeypatch.setattr(builder, 'WORKER', root / 'tools/worker.py')
    monkeypatch.setattr(builder.intake, 'trusted', lambda *args, **kwargs: None)
    monkeypatch.setattr(builder.intake, 'take_lock', lambda: builder.os.open(lock, builder.os.O_RDONLY))
    monkeypatch.setattr(builder, 'ensure_builder_idle', lambda uid: None)
    monkeypatch.setattr(builder.pwd, 'getpwnam', lambda name: SimpleNamespace(
        pw_uid=12345, pw_gid=12345, pw_shell='/usr/sbin/nologin'))
    monkeypatch.setattr(builder.os, 'getgrouplist', lambda *args: [12345])
    (root / 'shared').chmod(0o750)
    with pytest.raises(builder.BuildError, match='already exists'):
        builder.build(rev, digest)
    assert (existing / 'sentinel').read_text(encoding='ascii') == 'preserve'
    assert not list((root / 'build-work').iterdir())


def test_capacity_refuses_insufficient_space(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(builder.shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    with pytest.raises(builder.BuildError, match='insufficient disk'):
        builder.check_capacity()


def test_capacity_does_not_count_child_twice(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    child = work / 'stage'
    child.mkdir(parents=True)
    releases = tmp_path / 'releases'
    releases.mkdir()
    calls = []
    def disk_bytes(path):
        calls.append(path)
        return 20
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(builder, 'RELEASES', releases)
    monkeypatch.setattr(builder, 'BUILD_BYTES', 25)
    monkeypatch.setattr(builder, 'disk_bytes', disk_bytes)
    monkeypatch.setattr(builder.shutil, 'disk_usage', lambda path: SimpleNamespace(free=10**12))
    builder.check_capacity(child, work, child)
    assert calls == [releases, work]


def test_unloaded_unit_requires_reachable_manager(monkeypatch):
    responses = iter([SimpleNamespace(returncode=1, stdout=''),
                      SimpleNamespace(returncode=0, stdout='')])
    monkeypatch.setattr(builder.subprocess, 'run', lambda *args, **kwargs: next(responses))
    assert builder.unit_state('test-unit')['LoadState'] == 'not-found'


def test_failed_unit_query_does_not_hide_loaded_unit(monkeypatch):
    responses = iter([SimpleNamespace(returncode=1, stdout=''),
                      SimpleNamespace(returncode=0, stdout='test-unit.service loaded active running\n')])
    monkeypatch.setattr(builder.subprocess, 'run', lambda *args, **kwargs: next(responses))
    with pytest.raises(builder.BuildError, match='cannot inspect'):
        builder.unit_state('test-unit')


def test_pending_jobs_match_exact_unit(monkeypatch):
    result = SimpleNamespace(stdout='12 test-unit-extra.service start running\n'
                                    '13 test-unit.service start waiting\n')
    monkeypatch.setattr(builder.subprocess, 'run', lambda *args, **kwargs: result)
    assert builder.has_pending_job('test-unit')
    assert not builder.has_pending_job('test')


@pytest.mark.parametrize('unit', ['/run/test/venv-child', 'test unit', 'test.service', 'test.mount',
                                  'test.socket', '../test', ''])
def test_invalid_unit_name_is_rejected_before_systemd(unit, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('invalid unit must not query or start systemd')
    monkeypatch.setattr(builder.subprocess, 'run', unexpected)
    with pytest.raises(builder.BuildError, match='invalid transient service name'):
        builder.ensure_unit_available(unit)


def test_existing_unit_is_rejected(monkeypatch):
    result = SimpleNamespace(stdout='test-unit.service loaded active running\n')
    monkeypatch.setattr(builder.subprocess, 'run', lambda *args, **kwargs: result)
    with pytest.raises(builder.BuildError, match='already in use'):
        builder.ensure_unit_available('test-unit')
