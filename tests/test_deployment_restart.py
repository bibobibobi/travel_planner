import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('fcntl')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy' / 'server'))
import deployment_controller as controller
import deployment_transaction as transaction

OLD, NEW = 'a' * 40, 'b' * 40


@pytest.fixture
def pending(tmp_path, monkeypatch):
    store = transaction.StateStore(tmp_path)
    store.save({'current': OLD, 'previous': None, 'transaction': {'old': OLD, 'new': NEW}})
    monkeypatch.setattr(controller, 'open_store', lambda: store)
    return store


def test_restart_client_timeout_preserves_uncertainty(pending, monkeypatch):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(controller.subprocess, 'run', timeout)
    with pytest.raises(controller.RestartUncertain, match='timed out'):
        controller.restart_and_check()
    assert pending.load()['transaction']['restart_uncertain'] is True
    with pytest.raises(transaction.TransactionError, match='uncertain'):
        transaction.recover(pending, lambda revision: pytest.fail('must not switch'), lambda: True)


def test_completed_restart_with_pending_systemd_job_is_uncertain(pending, monkeypatch):
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: False)
    with pytest.raises(controller.RestartUncertain, match='uncertain'):
        controller.restart_and_check()
    assert pending.load()['transaction']['restart_uncertain'] is True


def test_completed_restart_clears_marker_before_health_failure(pending, monkeypatch):
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: True)
    assert controller.restart_and_check() is False
    assert pending.load()['transaction']['restart_uncertain'] is False


@pytest.mark.parametrize(('show', 'jobs', 'expected'), [
    ('Job=\nActiveState=active\n', '', True),
    ('Job=7\nActiveState=active\n', '', False),
    ('Job=\nActiveState=activating\n', '', False),
    ('Job=\nActiveState=active\n', '8 travel.service restart running\n', False),
    ('ActiveState=active\n', '', False),
])
def test_systemd_job_evidence_is_fail_closed(monkeypatch, show, jobs, expected):
    responses = iter([SimpleNamespace(stdout=show, returncode=0), SimpleNamespace(stdout=jobs)])
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: next(responses))
    assert controller.no_service_jobs() is expected


def test_admin_recovery_checks_stop_then_recovers(pending, monkeypatch):
    state = pending.load()
    state['transaction']['restart_uncertain'] = True
    pending.save(state)
    monkeypatch.setattr(controller, 'current_revision', lambda: NEW)
    monkeypatch.setattr(controller, 'validate_release', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, 'service_cgroup', lambda: Path('/test/cgroup'))
    monkeypatch.setattr(controller, 'service_fully_stopped', lambda path: True)
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: True)
    switched = []
    monkeypatch.setattr(controller, 'switch', switched.append)
    monkeypatch.setattr(controller, 'restart_and_check', lambda: True)
    controller.recover_uncertain()
    assert switched == [OLD]
    assert pending.load()['transaction'] is None


def test_admin_recovery_keeps_uncertainty_when_stop_fails(pending, monkeypatch):
    state = pending.load()
    state['transaction']['restart_uncertain'] = True
    pending.save(state)
    monkeypatch.setattr(controller, 'current_revision', lambda: NEW)
    monkeypatch.setattr(controller, 'validate_release', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, 'service_cgroup', lambda: Path('/test/cgroup'))
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(controller.RestartUncertain, match='unable to confirm service stop'):
        controller.recover_uncertain()
    assert pending.load()['transaction']['restart_uncertain'] is True


def test_admin_recovery_refuses_pending_systemd_job(pending, monkeypatch):
    state = pending.load()
    state['transaction']['restart_uncertain'] = True
    pending.save(state)
    monkeypatch.setattr(controller, 'current_revision', lambda: NEW)
    monkeypatch.setattr(controller, 'validate_release', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, 'service_cgroup', lambda: Path('/test/cgroup'))
    monkeypatch.setattr(controller, 'service_fully_stopped', lambda path: False)
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: False)
    monkeypatch.setattr(controller, 'switch', lambda revision: pytest.fail('must not switch'))
    with pytest.raises(controller.RestartUncertain, match='unable to confirm service stop'):
        controller.recover_uncertain()
    assert pending.load()['transaction']['restart_uncertain'] is True


def test_admin_recovery_refuses_unrelated_current(pending, monkeypatch):
    state = pending.load()
    state['transaction']['restart_uncertain'] = True
    pending.save(state)
    monkeypatch.setattr(controller, 'current_revision', lambda: 'c' * 40)
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: pytest.fail('must not stop'))
    with pytest.raises(controller.DeploymentError, match='does not match'):
        controller.recover_uncertain()
    assert pending.load()['transaction']['restart_uncertain'] is True


def test_admin_recovery_refuses_active_service_even_when_no_jobs(pending, monkeypatch):
    state = pending.load()
    state['transaction']['restart_uncertain'] = True
    pending.save(state)
    monkeypatch.setattr(controller, 'current_revision', lambda: NEW)
    monkeypatch.setattr(controller, 'validate_release', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, 'service_cgroup', lambda: Path('/test/cgroup'))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: True)
    monkeypatch.setattr(controller, 'service_fully_stopped', lambda path: False)
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(controller, 'switch', lambda revision: pytest.fail('must not switch'))
    with pytest.raises(controller.RestartUncertain, match='unable to confirm service stop'):
        controller.recover_uncertain()
    assert pending.load()['transaction']['restart_uncertain'] is True


@pytest.mark.parametrize(('active', 'substate', 'pid', 'populated', 'expected'), [
    ('inactive', 'dead', '0', '0', True),
    ('active', 'running', '123', '1', False),
    ('active', 'exited', '0', '0', False),
    ('inactive', 'dead', '123', '0', False),
    ('inactive', 'dead', '0', '1', False),
    ('deactivating', 'stop', '0', '0', False),
])
def test_stopped_service_requires_all_evidence(tmp_path, monkeypatch, active, substate, pid, populated, expected):
    group = tmp_path / 'group'
    group.mkdir()
    (group / 'cgroup.events').write_text(f'populated {populated}\n', encoding='ascii')
    text = (f'LoadState=loaded\nActiveState={active}\nSubState={substate}\nMainPID={pid}\n'
            'ControlGroup=/system.slice/travel.service\nSlice=system.slice\nDelegate=no\n')
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=text))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: True)
    assert controller.service_fully_stopped(group) is expected


def test_stopped_service_requires_readable_cgroup_evidence(tmp_path, monkeypatch):
    group = tmp_path / 'group'
    group.mkdir()
    text = ('LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\n'
            'ControlGroup=\nSlice=system.slice\nDelegate=no\n')
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=text))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: True)
    assert not controller.service_fully_stopped(group)


def test_stopped_service_rejects_pending_job(tmp_path, monkeypatch):
    group = tmp_path / 'group'
    group.mkdir()
    (group / 'cgroup.events').write_text('populated 0\n', encoding='ascii')
    text = ('LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\n'
            'ControlGroup=\nSlice=system.slice\nDelegate=no\n')
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=text))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: False)
    assert not controller.service_fully_stopped(group)


def test_unloaded_service_requires_absent_unit_and_cgroup(tmp_path, monkeypatch):
    group = tmp_path / 'gone'
    responses = iter([SimpleNamespace(returncode=1, stdout=''),
                      SimpleNamespace(returncode=0, stdout='')])
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: True)
    assert controller.service_fully_stopped(group)


def test_unreadable_state_cannot_hide_loaded_service(tmp_path, monkeypatch):
    group = tmp_path / 'gone'
    responses = iter([SimpleNamespace(returncode=1, stdout=''),
                      SimpleNamespace(returncode=0, stdout='travel.service loaded active running\n')])
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(controller, 'no_service_jobs', lambda: True)
    assert not controller.service_fully_stopped(group)


@pytest.mark.parametrize(('slice_name', 'delegate', 'cgroup', 'user'), [
    ('other.slice', 'no', '/system.slice/travel.service', 'travel-app'),
    ('system.slice', 'yes', '/system.slice/travel.service', 'travel-app'),
    ('system.slice', 'no', '/other.slice/travel.service', 'travel-app'),
    ('system.slice', 'no', '/system.slice/travel.service', 'root'),
])
def test_service_cgroup_rejects_unverifiable_identity(monkeypatch, slice_name, delegate, cgroup, user):
    text = (f'LoadState=loaded\nSlice={slice_name}\nDelegate={delegate}\n'
            f'User={user}\nControlGroup={cgroup}\n')
    monkeypatch.setattr(controller.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=text))
    with pytest.raises(controller.RestartUncertain, match='cannot establish'):
        controller.service_cgroup()
