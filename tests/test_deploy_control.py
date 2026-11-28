from unittest.mock import patch

import pytest

from deploy.server import travel_deploy_control as control

REV = "a" * 40
DIGEST = "b" * 64


def test_controller_is_disabled(capsys):
    assert control.main([]) == 1
    assert "disabled" in capsys.readouterr().err


def test_input_is_strict():
    assert control.checked(REV, control.SHA, "revision") == REV
    with pytest.raises(control.DeployError):
        control.checked("../" + REV, control.SHA, "revision")
    with pytest.raises(control.DeployError):
        control.checked("A" * 64, control.DIGEST, "sha256")


def test_successful_deploy_builds_switches_and_restarts():
    with patch.object(control, "current_revision", return_value="c" * 40), \
         patch.object(control, "build_release") as build, \
         patch.object(control, "switch_current") as switch, \
         patch.object(control, "restart_and_check", return_value=True):
        control.deploy(REV, DIGEST)
    build.assert_called_once_with(REV, DIGEST)
    switch.assert_called_once_with(REV)


def test_failed_health_rolls_back_and_fails_operation():
    old = "c" * 40
    with (
        patch.object(control, "current_revision", return_value=old),
        patch.object(control, "build_release"),
        patch.object(control, "switch_current") as switch,
        patch.object(control, "restart_and_check", side_effect=[False, True]),
        pytest.raises(control.DeployError, match="restored"),
    ):
        control.deploy(REV, DIGEST)
    assert [call.args[0] for call in switch.call_args_list] == [REV, old]


def test_failed_rollback_reports_failure():
    with (
        patch.object(control, "current_revision", return_value="c" * 40),
        patch.object(control, "switch_current"),
        patch.object(control, "restart_and_check", side_effect=[False, False]),
        pytest.raises(control.DeployError, match="health"),
    ):
        control.rollback(REV)


def test_cleanup_is_dry_run_only(tmp_path):
    (tmp_path / REV).mkdir()
    with patch.object(control, "RELEASES", tmp_path), patch.object(control, "current_revision", return_value=None):
        assert control.cleanup(True) == [REV]
        with pytest.raises(control.DeployError):
            control.cleanup(False)


def test_lock_serializes_concurrent_operations(tmp_path):
    if control.fcntl is None:
        pytest.skip("flock requires Linux")
    with patch.object(control, "LOCK", tmp_path / "lock"), control.lifecycle_lock():
        assert (tmp_path / "lock").exists()
