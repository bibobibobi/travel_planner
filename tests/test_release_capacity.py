
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Release builder requires Linux",
)

if sys.platform != "linux":
    pytest.skip("Linux-only deployment module", allow_module_level=True)

SERVER_DIR = Path(__file__).resolve().parents[1] / "deploy" / "server"
sys.path.insert(0, str(SERVER_DIR))

import release_builder as builder


def du_result(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["du"],
        returncode=code,
        stdout=stdout,
        stderr=stderr,
    )


def transient_error():
    return du_result(
        code=1,
        stderr="du: cannot access 'temporary-file': "
        "No such file or directory\n",
    )


@pytest.fixture(autouse=True)
def disable_sleep(monkeypatch):
    monkeypatch.setattr(builder.time, "sleep", Mock())


def test_disk_bytes_success(monkeypatch, tmp_path):
    run = Mock(return_value=du_result(stdout="1024\t/path\n"))
    monkeypatch.setattr(builder.subprocess, "run", run)

    assert builder.disk_bytes(tmp_path) == 1024
    assert run.call_count == 1


def test_disk_bytes_retry_success(monkeypatch, tmp_path):
    run = Mock(side_effect=[
        transient_error(),
        du_result(stdout="2048\t/path\n"),
    ])
    monkeypatch.setattr(builder.subprocess, "run", run)

    assert builder.disk_bytes(tmp_path) == 2048
    assert run.call_count == 2


def test_disk_bytes_retry_exhausted(monkeypatch, tmp_path):
    run = Mock(return_value=transient_error())
    monkeypatch.setattr(builder.subprocess, "run", run)

    with pytest.raises(builder.BuildError):
        builder.disk_bytes(tmp_path)

    assert run.call_count == 3


@pytest.mark.parametrize("message", [
    "du: cannot access 'file': Permission denied",
    "du: cannot access 'file': Input/output error",
])
def test_disk_bytes_permanent_error(
    monkeypatch, tmp_path, message
):
    run = Mock(return_value=du_result(code=1, stderr=message))
    monkeypatch.setattr(builder.subprocess, "run", run)

    with pytest.raises(builder.BuildError, match=message):
        builder.disk_bytes(tmp_path)

    assert run.call_count == 1


def test_disk_bytes_mixed_errors(monkeypatch, tmp_path):
    run = Mock(return_value=du_result(
        code=1,
        stderr=(
            "du: cannot access 'file1': No such file or directory\n"
            "du: cannot access 'file2': Permission denied\n"
        ),
    ))
    monkeypatch.setattr(builder.subprocess, "run", run)

    with pytest.raises(builder.BuildError):
        builder.disk_bytes(tmp_path)

    assert run.call_count == 1


def test_disk_bytes_missing_root(monkeypatch, tmp_path):
    run = Mock(return_value=transient_error())
    monkeypatch.setattr(builder.subprocess, "run", run)

    with pytest.raises(builder.BuildError):
        builder.disk_bytes(tmp_path / "missing")

    assert run.call_count == 1


def test_releases_capacity_exceeded(monkeypatch):
    monkeypatch.setattr(
        builder.shutil,
        "disk_usage",
        Mock(return_value=Mock(free=10 * 1024**3)),
    )
    monkeypatch.setattr(
        builder,
        "disk_bytes",
        Mock(return_value=builder.RELEASE_BYTES + 1),
    )

    with pytest.raises(
        builder.BuildError,
        match="releases capacity exceeded",
    ):
        builder.check_capacity()


def test_insufficient_free_space(monkeypatch):
    monkeypatch.setattr(
        builder.shutil,
        "disk_usage",
        Mock(return_value=Mock(free=builder.FREE_BYTES - 1)),
    )

    with pytest.raises(
        builder.BuildError,
        match="insufficient disk space",
    ):
        builder.check_capacity()


def test_build_capacity_exceeded(monkeypatch, tmp_path):
    monkeypatch.setattr(
        builder.shutil,
        "disk_usage",
        Mock(return_value=Mock(free=10 * 1024**3)),
    )
    monkeypatch.setattr(
        builder,
        "disk_bytes",
        Mock(side_effect=[0, builder.BUILD_BYTES + 1]),
    )

    with pytest.raises(
        builder.BuildError,
        match="build capacity exceeded",
    ):
        builder.check_capacity(tmp_path)
