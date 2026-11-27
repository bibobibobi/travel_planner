import concurrent.futures
import os
import stat
import subprocess
import sys
import tarfile
from types import SimpleNamespace
from unittest import mock

import pytest
from test_validate_artifact import SHA, digest, valid_files, write_archive

from scripts import extract_artifact as extractor
from scripts import validate_artifact as validator


@pytest.fixture
def setup_artifact(tmp_path):
    archive = tmp_path / "artifact.tar.gz"
    write_archive(archive)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    return archive, staging


def extract(archive, staging, checksum=None):
    return extractor.extract_artifact(archive, SHA, checksum or digest(archive), staging)


def test_extracts_all_contents_and_ignores_metadata(tmp_path):
    archive = tmp_path / "artifact.tar.gz"
    files = valid_files()
    files["dist/圖片/檔案.png"] = b"image"
    import io
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.uid = member.gid = 1234
            member.mode = 0o7777
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    result = extract(archive, staging)
    root = staging / SHA
    assert result["FILE_COUNT"] == len(files)
    assert result["TOTAL_BYTES"] == sum(map(len, files.values()))
    for name, contents in files.items():
        assert (root / name).read_bytes() == contents
        if os.name == "posix":
            assert stat.S_IMODE((root / name).stat().st_mode) == 0o600
    if os.name == "posix":
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o700
                   for p in [root, *(p for p in root.rglob("*") if p.is_dir())])


def test_wrong_hash_no_publication(setup_artifact):
    archive, staging = setup_artifact
    with pytest.raises(validator.ValidationError):
        extract(archive, staging, "0" * 64)
    assert list(staging.iterdir()) == []


@pytest.mark.parametrize("kind", ["path", "symlink", "hardlink", "fifo"])
def test_invalid_archive_does_not_publish(setup_artifact, kind):
    archive, staging = setup_artifact
    if kind == "path":
        files = valid_files()
        files["../escape"] = b"x"
        write_archive(archive, files)
    else:
        member = tarfile.TarInfo("dist/bad.js")
        member.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                       "fifo": tarfile.FIFOTYPE}[kind]
        write_archive(archive, members=[member])
    with pytest.raises(validator.ValidationError):
        extract(archive, staging)
    assert list(staging.iterdir()) == []


def test_source_replaced_after_validation_uses_snapshot(setup_artifact, monkeypatch):
    archive, staging = setup_artifact
    expected = digest(archive)
    original = validator.validate_snapshot
    calls = 0
    def validate_and_replace(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            archive.write_bytes(b"replacement")
        return result
    monkeypatch.setattr(validator, "validate_snapshot", validate_and_replace)
    extractor.extract_artifact(archive, SHA, expected, staging)
    assert (staging / SHA / "app.py").read_bytes() == valid_files()["app.py"]


def test_limits_are_enforced(setup_artifact, monkeypatch):
    archive, staging = setup_artifact
    monkeypatch.setattr(validator, "MAX_CONTENT_BYTES", 1)
    with pytest.raises(validator.ValidationError, match="content"):
        extract(archive, staging)
    assert list(staging.iterdir()) == []


def test_existing_version_preserved(setup_artifact):
    archive, staging = setup_artifact
    existing = staging / SHA
    existing.mkdir()
    (existing / "keep").write_text("original")
    with pytest.raises((extractor.ExtractionError, OSError)):
        extract(archive, staging)
    assert (existing / "keep").read_text() == "original"
    assert sorted(p.name for p in staging.iterdir()) == [SHA]


def test_concurrent_publish_no_overwrite(setup_artifact):
    archive, staging = setup_artifact
    def run():
        try:
            return extract(archive, staging)
        except (extractor.ExtractionError, OSError):
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(r is not None for r in results) == 1
    assert sorted(p.name for p in staging.iterdir()) == [SHA]
    assert (staging / SHA / "app.py").read_bytes() == valid_files()["app.py"]


def test_unsafe_staging_rejected(setup_artifact, tmp_path):
    archive, staging = setup_artifact
    with pytest.raises(OSError):
        extract(archive, staging / "missing")
    link = tmp_path / "link"
    try:
        link.symlink_to(staging, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(extractor.ExtractionError):
        extract(archive, link)


@pytest.mark.parametrize("function", ["open_output", "publish"])
def test_failure_cleans_temporary_directory(setup_artifact, function):
    archive, staging = setup_artifact
    with (mock.patch.object(extractor, function, side_effect=OSError("simulated")),
          pytest.raises((OSError, validator.ValidationError))):
        extract(archive, staging)
    assert list(staging.iterdir()) == []


def test_write_failure_after_partial_output_is_cleaned(setup_artifact, monkeypatch):
    archive, staging = setup_artifact
    original = extractor.open_output
    class FailingOutput:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, data):
            self.stream.write(data[:1])
            raise OSError("simulated disk full")
    monkeypatch.setattr(extractor, "open_output", lambda root, name: FailingOutput(original(root, name)))
    with pytest.raises(validator.ValidationError):
        extract(archive, staging)
    assert list(staging.iterdir()) == []


def test_cli_success_and_failure(setup_artifact):
    archive, staging = setup_artifact
    cmd = [sys.executable, "scripts/extract_artifact.py", "--artifact", str(archive),
           "--revision", SHA, "--sha256", digest(archive), "--staging-dir", str(staging)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    for value in ("EXTRACTION_OK", f"REVISION: {SHA}", f"SHA256: {digest(archive)}",
                  "FILE_COUNT: 8", "TOTAL_BYTES:", "STAGING_PATH:", str(staging)):
        assert value in result.stdout
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert result.stderr == "Extraction failed: invalid artifact, staging path, or filesystem operation\n"
    assert str(archive) not in result.stderr and str(staging) not in result.stderr


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership and mode checks")
@pytest.mark.parametrize("mode", [0o750, 0o701, 0o777])
def test_insecure_staging_mode_rejected(setup_artifact, mode):
    archive, staging = setup_artifact
    staging.chmod(mode)
    with pytest.raises(extractor.ExtractionError, match="private"):
        extract(archive, staging)
    assert stat.S_IMODE(staging.stat().st_mode) == mode
    assert list(staging.iterdir()) == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership check")
def test_staging_wrong_owner_rejected(setup_artifact, monkeypatch):
    _, staging = setup_artifact
    real_geteuid = os.geteuid()
    monkeypatch.setattr(extractor.os, "geteuid", lambda: real_geteuid + 1)
    with pytest.raises(extractor.ExtractionError, match="owned"):
        extractor.check_staging(staging)


@pytest.mark.parametrize("kind", ["extra_dir", "extra_file", "hardlink", "changed", "oversize"])
def test_unexpected_output_prevents_publication(setup_artifact, monkeypatch, kind):
    archive, staging = setup_artifact
    original = extractor.verify_written
    def tamper(root, expected):
        if kind == "extra_dir":
            (root / "extra").mkdir()
        elif kind == "extra_file":
            (root / "extra").write_bytes(b"x")
        elif kind == "hardlink":
            os.link(root / "app.py", root / "extra")
        elif kind == "changed":
            (root / "app.py").write_bytes(b"bad")
        else:
            (root / "app.py").write_bytes(b"too large")
        original(root, expected)
    monkeypatch.setattr(extractor, "verify_written", tamper)
    with pytest.raises(extractor.ExtractionError):
        extract(archive, staging)
    assert list(staging.iterdir()) == []


def test_output_reparse_point_prevents_publication(setup_artifact, monkeypatch):
    archive, staging = setup_artifact
    original_verify = extractor.verify_written
    original_lstat = os.lstat
    def tamper(root, expected):
        def lstat(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if str(path) == str(root / "app.py"):
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with monkeypatch.context() as patch:
            patch.setattr(extractor.os, "lstat", lstat)
            original_verify(root, expected)
    monkeypatch.setattr(extractor, "verify_written", tamper)
    with pytest.raises(extractor.ExtractionError):
        extract(archive, staging)
    assert list(staging.iterdir()) == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux output permissions")
@pytest.mark.parametrize("kind", ["file_mode", "dir_mode", "root_mode", "owner", "file_owner",
                                  "dir_owner", "fifo", "symlink"])
def test_unsafe_linux_output_prevents_publication(setup_artifact, monkeypatch, kind):
    archive, staging = setup_artifact
    original = extractor.verify_written
    def tamper(root, expected):
        if kind == "file_mode":
            (root / "app.py").chmod(0o644)
        elif kind == "dir_mode":
            (root / "dist").chmod(0o755)
        elif kind == "root_mode":
            root.chmod(0o755)
        elif kind == "owner":
            uid = os.geteuid()
            monkeypatch.setattr(extractor.os, "geteuid", lambda: uid + 1)
        elif kind in ("file_owner", "dir_owner"):
            target = root / ("app.py" if kind == "file_owner" else "dist")
            real_lstat = os.lstat
            def altered_lstat(path, *args, **kwargs):
                info = real_lstat(path, *args, **kwargs)
                if str(path) == str(target):
                    return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid + 1,
                                           st_nlink=info.st_nlink, st_size=info.st_size)
                return info
            with monkeypatch.context() as patch:
                patch.setattr(extractor.os, "lstat", altered_lstat)
                original(root, expected)
            return
        elif kind == "fifo":
            os.mkfifo(root / "extra")
        else:
            (root / "extra").symlink_to(root / "app.py")
        original(root, expected)
    monkeypatch.setattr(extractor, "verify_written", tamper)
    with pytest.raises(extractor.ExtractionError):
        extract(archive, staging)
    assert list(staging.iterdir()) == []


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="POSIX only")
def test_root_is_rejected(setup_artifact, monkeypatch):
    archive, staging = setup_artifact
    monkeypatch.setattr(extractor.os, "geteuid", lambda: 0)
    with pytest.raises(extractor.ExtractionError, match="root"):
        extract(archive, staging)
