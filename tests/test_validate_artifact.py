import gzip
import hashlib
import io
import os
import subprocess
import sys
import tarfile

import pytest

from scripts import validate_artifact as validator

SHA = "a" * 40


def write_archive(path, files=None, members=(), mode="w:gz"):
    files = valid_files() if files is None else files
    with tarfile.open(path, mode, format=tarfile.PAX_FORMAT) as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        for entry in members:
            archive.addfile(entry)


def valid_files():
    return {
        "app.py": b"app", "websocket_worker.py": b"worker",
        "requirements.txt": b"flask", "requirements-prod.txt": b"gunicorn",
        "REVISION": (SHA + "\n").encode(), "dist/index.html": b"<html>",
        "dist/assets/app.js": b"console.log(1)", "dist/assets/style.css": b"body{}",
    }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(path, revision=SHA, checksum=None):
    return validator.validate_artifact(path, revision, checksum or digest(path))


def test_valid_artifact_and_unicode_path(tmp_path):
    archive = tmp_path / "valid.tar.gz"
    files = valid_files()
    files["dist/資產/圖片.png"] = b"image"
    write_archive(archive, files)
    result = validate(archive)
    assert result["FILE_COUNT"] == len(files)
    assert result["TOTAL_BYTES"] == sum(map(len, files.values()))


def test_bad_checksum_and_revision_are_rejected(tmp_path):
    archive = tmp_path / "valid.tar.gz"
    write_archive(archive)
    with pytest.raises(validator.ValidationError, match="SHA256"):
        validate(archive, checksum="0" * 64)
    with pytest.raises(validator.ValidationError, match="REVISION"):
        validate(archive, revision="b" * 40)
    with pytest.raises(validator.ValidationError, match="revision must"):
        validate(archive, revision="A" * 40)


@pytest.mark.parametrize("name", sorted(validator.REQUIRED) + ["dist/assets/app.js"])
def test_missing_or_empty_required_files(tmp_path, name):
    archive = tmp_path / "bad.tar.gz"
    files = valid_files()
    files.pop(name)
    write_archive(archive, files)
    with pytest.raises(validator.ValidationError):
        validate(archive)
    files = valid_files()
    files[name] = b""
    write_archive(archive, files)
    with pytest.raises(validator.ValidationError):
        validate(archive)


@pytest.mark.parametrize("name", ["../app.py", "/app.py", "dist\\app.js", "dist/.env",
                                   "dist/node_modules/a.js", "dist/backup.sql", "dist/CON.js"])
def test_unsafe_or_forbidden_paths(tmp_path, name):
    archive = tmp_path / "bad.tar.gz"
    files = valid_files()
    files[name] = b"x"
    write_archive(archive, files)
    with pytest.raises(validator.ValidationError):
        validate(archive)


@pytest.mark.parametrize("extra", [("dist/A.js", "dist/a.js"), ("dist/file.js", "dist/file.js/a.js"),
                                   ("dist/Assets/a.js", "dist/assets/b.js")])
def test_case_and_component_conflicts(tmp_path, extra):
    archive = tmp_path / "conflict.tar.gz"
    files = valid_files()
    files[extra[0]] = b"x"
    files[extra[1]] = b"x"
    write_archive(archive, files)
    with pytest.raises(validator.ValidationError, match="conflicting"):
        validate(archive)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE,
                                   tarfile.CHRTYPE, tarfile.GNUTYPE_SPARSE])
def test_special_archive_members_are_rejected(tmp_path, kind):
    archive = tmp_path / "special.tar.gz"
    member = tarfile.TarInfo("dist/bad.js")
    member.type = kind
    member.linkname = "elsewhere"
    write_archive(archive, members=[member])
    with pytest.raises(validator.ValidationError, match="non-regular|forbidden"):
        validate(archive)


def test_empty_corrupt_and_trailing_data(tmp_path):
    empty = tmp_path / "empty.tar.gz"
    empty.write_bytes(b"")
    with pytest.raises(validator.ValidationError, match="empty"):
        validate(empty, checksum=hashlib.sha256(b"").hexdigest())
    corrupt = tmp_path / "corrupt.tar.gz"
    corrupt.write_bytes(b"not gzip")
    with pytest.raises(validator.ValidationError):
        validate(corrupt)
    archive = tmp_path / "tail.tar.gz"
    write_archive(archive)
    archive.write_bytes(archive.read_bytes() + b"trailing")
    with pytest.raises(validator.ValidationError, match="trailing"):
        validate(archive)
    raw_tail = tmp_path / "raw-tail.tar.gz"
    write_archive(raw_tail)
    raw_tail.write_bytes(gzip.compress(gzip.decompress(raw_tail.read_bytes()) + b"trailing"))
    with pytest.raises(validator.ValidationError, match="tar archive has unexpected"):
        validate(raw_tail)


def test_nonzero_tail_inside_tar_read_ahead_is_rejected(tmp_path):
    archive = tmp_path / "buffered-tail.tar.gz"
    write_archive(archive)
    raw = bytearray(gzip.decompress(archive.read_bytes()))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        last = tar.getmembers()[-1]
        end = last.offset_data + ((last.size + 511) // 512) * 512
    raw[end + 1024:end + 1028] = b"evil"
    archive.write_bytes(gzip.compress(raw))
    with pytest.raises(validator.ValidationError):
        validate(archive)


@pytest.mark.parametrize("variant", ["no_end", "one_end", "header", "member", "padding",
                                      "large_tail", "second_tar", "second_gzip"])
def test_tar_framing_rejects_truncation_and_extra_archives(tmp_path, variant):
    archive = tmp_path / "framing.tar.gz"
    write_archive(archive)
    original = archive.read_bytes()
    raw = gzip.decompress(original)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        last = tar.getmembers()[-1]
    end = last.offset_data + ((last.size + 511) // 512) * 512
    variants = {
        "no_end": raw[:end], "one_end": raw[:end + 512],
        "header": raw[:100], "member": raw[:last.offset_data + last.size - 1],
        "padding": raw[:last.offset_data + last.size + 1],
        "large_tail": raw[:end + 1024] + b"x" * 100000,
        "second_tar": raw[:end + 1024] + raw,
    }
    archive.write_bytes(original + original if variant == "second_gzip" else gzip.compress(variants[variant]))
    with pytest.raises(validator.ValidationError):
        validate(archive)


def test_tar_end_and_zero_padding_are_valid(tmp_path):
    archive = tmp_path / "padding.tar.gz"
    write_archive(archive)
    raw = gzip.decompress(archive.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        last = tar.getmembers()[-1]
    end = last.offset_data + ((last.size + 511) // 512) * 512
    for padding in (1024, 4096):
        archive.write_bytes(gzip.compress(raw[:end] + bytes(padding)))
        validate(archive)


@pytest.mark.parametrize("key", ["size", "GNU.sparse.map", "comment"])
def test_pax_unsupported_override_rejected(tmp_path, key):
    archive = tmp_path / "pax-invalid.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        member = tarfile.TarInfo("app.py")
        member.size = 1
        member.pax_headers = {key: "1"}
        tar.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(validator.ValidationError, match="PAX"):
        validate(archive)


def test_metadata_and_physical_header_limits(tmp_path, monkeypatch):
    archive = tmp_path / "metadata.tar.gz"
    write_archive(archive)
    monkeypatch.setattr(validator, "MAX_HEADERS", 7)
    with pytest.raises(validator.ValidationError, match="headers"):
        validate(archive)
    monkeypatch.setattr(validator, "MAX_HEADERS", 2000)
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        member = tarfile.TarInfo("app.py")
        member.pax_headers = {"mtime": "1" * 100}
        tar.addfile(member)
    monkeypatch.setattr(validator, "MAX_METADATA_BYTES", 32)
    with pytest.raises(validator.ValidationError, match="metadata"):
        validate(archive)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO and symlink")
@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_replacement_between_lstat_and_open_is_rejected(tmp_path, kind):
    artifact = tmp_path / "source"
    artifact.write_bytes(b"source")
    code = '''import os, sys
from scripts import validate_artifact as v
p, kind = sys.argv[1:]
original = v.os.lstat
def replace(path):
    result = original(path)
    os.unlink(path)
    if kind == "fifo": os.mkfifo(path)
    else: os.symlink("missing", path)
    return result
v.os.lstat = replace
try:
    v.snapshot_artifact(p, "0" * 64)
except v.ValidationError:
    sys.exit(0)
sys.exit(1)
'''
    result = subprocess.run([sys.executable, "-c", code, str(artifact), kind],
                            capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr


def test_size_member_count_path_and_stream_limits(tmp_path, monkeypatch):
    archive = tmp_path / "limits.tar.gz"
    files = valid_files()
    files["dist/a.js"] = b"12345"
    write_archive(archive, files)
    monkeypatch.setattr(validator, "MAX_MEMBER_BYTES", 4)
    with pytest.raises(validator.ValidationError, match="member"):
        validate(archive)
    monkeypatch.setattr(validator, "MAX_MEMBER_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr(validator, "MAX_MEMBERS", 2)
    with pytest.raises(validator.ValidationError, match="too many"):
        validate(archive)
    monkeypatch.setattr(validator, "MAX_MEMBERS", 1000)
    monkeypatch.setattr(validator, "MAX_STREAM_BYTES", 100)
    with pytest.raises(validator.ValidationError, match="decompressed"):
        validate(archive)
    monkeypatch.setattr(validator, "MAX_STREAM_BYTES", 60 * 1024 * 1024)
    monkeypatch.setattr(validator, "MAX_PATH_BYTES", 10)
    with pytest.raises(validator.ValidationError, match="unsafe path"):
        validate(archive)


def test_pax_metadata_counts_against_decompressed_stream_limit(tmp_path, monkeypatch):
    archive = tmp_path / "pax.tar.gz"
    files = valid_files()
    normal = tmp_path / "normal.tar.gz"
    write_archive(normal, files)
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as output:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            if name == "dist/assets/app.js":
                member.pax_headers = {"comment": "x" * 20000}
            output.addfile(member, io.BytesIO(data))
    limit = len(gzip.decompress(normal.read_bytes()))
    assert len(gzip.decompress(archive.read_bytes())) > limit
    monkeypatch.setattr(validator, "MAX_STREAM_BYTES", limit)
    assert validate(normal)["FILE_COUNT"] == len(files)
    with pytest.raises(validator.ValidationError, match="decompressed"):
        validate(archive)


def test_compressed_limit_and_source_link_and_fifo(tmp_path, monkeypatch):
    archive = tmp_path / "valid.tar.gz"
    write_archive(archive)
    monkeypatch.setattr(validator, "MAX_COMPRESSED_BYTES", 1)
    with pytest.raises(validator.ValidationError, match="compressed"):
        validate(archive)
    monkeypatch.setattr(validator, "MAX_COMPRESSED_BYTES", 10 * 1024 * 1024)
    link = tmp_path / "link.tar.gz"
    try:
        link.symlink_to(archive)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(validator.ValidationError, match="non-linked|safely open"):
        validate(link)


def test_open_descriptor_isolated_from_later_path_replacement(tmp_path, monkeypatch):
    """The validator reads its one opened descriptor, not a later pathname target."""
    artifact = tmp_path / "artifact.tar.gz"
    write_archive(artifact)
    replacement = tmp_path / "replacement.tar.gz"
    replacement.write_bytes(b"replacement")
    original_bytes = artifact.read_bytes()
    real_open = validator.os.open

    def replace_after_open(path, flags):
        descriptor = real_open(path, flags)
        try:
            os.replace(replacement, artifact)
        except PermissionError:
            os.close(descriptor)
            pytest.skip("this Windows filesystem prevents replacing an open file")
        return descriptor

    monkeypatch.setattr(validator.os, "open", replace_after_open)
    try:
        snapshot, actual = validator.snapshot_artifact(artifact, hashlib.sha256(original_bytes).hexdigest())
    except validator.ValidationError as error:
        assert str(error) == "artifact source must be a non-linked regular file"
        return
    try:
        assert actual == hashlib.sha256(original_bytes).hexdigest()
        assert snapshot.read() == original_bytes
    finally:
        snapshot.close()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable on Windows")
def test_source_fifo_is_rejected(tmp_path):
    fifo = tmp_path / "artifact"
    os.mkfifo(fifo)
    result = subprocess.run([sys.executable, "scripts/validate_artifact.py", "--artifact", str(fifo),
                             "--revision", SHA, "--sha256", "0" * 64],
                            capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode != 0
    assert "non-linked regular file" in result.stderr


def test_source_hard_link_rejected(tmp_path):
    archive = tmp_path / "artifact.tar.gz"
    write_archive(archive)
    link = tmp_path / "hardlink.tar.gz"
    os.link(archive, link)
    with pytest.raises(validator.ValidationError, match="non-linked"):
        validate(link)


def test_duplicate_member_rejected(tmp_path):
    archive = tmp_path / "duplicate.tar.gz"
    member = tarfile.TarInfo("app.py")
    write_archive(archive, members=[member])
    with pytest.raises(validator.ValidationError, match="duplicate"):
        validate(archive)


def test_total_content_limit_boundary(tmp_path, monkeypatch):
    archive = tmp_path / "content.tar.gz"
    files = valid_files()
    write_archive(archive, files)
    total = sum(map(len, files.values()))
    monkeypatch.setattr(validator, "MAX_CONTENT_BYTES", total)
    monkeypatch.setattr(validator, "MAX_MEMBER_BYTES", max(map(len, files.values())))
    monkeypatch.setattr(validator, "MAX_STREAM_BYTES", len(gzip.decompress(archive.read_bytes())))
    assert validate(archive)["TOTAL_BYTES"] == total
    files["dist/extra.js"] = b"x"
    write_archive(archive, files)
    assert len(gzip.decompress(archive.read_bytes())) <= validator.MAX_STREAM_BYTES
    with pytest.raises(validator.ValidationError, match="content exceeds"):
        validate(archive)


def test_path_depth_boundary(tmp_path):
    archive = tmp_path / "depth.tar.gz"
    files = valid_files()
    name = "/".join(["dist"] + ["d"] * (validator.MAX_PATH_DEPTH - 2) + ["a.js"])
    files[name] = b"x"
    write_archive(archive, files)
    validate(archive)
    files[name.replace("dist/", "dist/d/", 1)] = b"x"
    write_archive(archive, files)
    with pytest.raises(validator.ValidationError, match="unsafe path"):
        validate(archive)


@pytest.mark.parametrize("kind", ["gzip", "tar"])
def test_truncated_stream_is_rejected(tmp_path, kind):
    archive = tmp_path / "truncated.tar.gz"
    write_archive(archive)
    compressed = archive.read_bytes()
    if kind == "gzip":
        archive.write_bytes(compressed[:-8])
    else:
        raw = gzip.decompress(compressed)
        archive.write_bytes(gzip.compress(raw[:600]))
    with pytest.raises(validator.ValidationError):
        validate(archive)


def test_cli_exit_codes(tmp_path):
    archive = tmp_path / "valid.tar.gz"
    write_archive(archive)
    command = [sys.executable, "scripts/validate_artifact.py", "--artifact", str(archive),
               "--revision", SHA, "--sha256", digest(archive)]
    good = subprocess.run(command, capture_output=True, text=True, check=False)
    assert good.returncode == 0 and "VALIDATION_OK" in good.stdout
    command[-1] = "0" * 64
    bad = subprocess.run(command, capture_output=True, text=True, check=False)
    assert bad.returncode != 0 and "Validation failed:" in bad.stderr
