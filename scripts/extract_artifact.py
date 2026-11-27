"""Validate and extract an artifact into a trusted staging directory."""

import argparse
import ctypes
import errno
import hashlib
import os
import stat
import sys
import tempfile
from pathlib import Path

if __package__:
    from . import validate_artifact as validator
else:
    import validate_artifact as validator


class ExtractionError(ValueError):
    """A non-sensitive extraction failure."""


def check_staging(path):
    """Reject symlinks/reparse points in the staging path; parents must be trusted."""
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        info = os.lstat(current)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400):
            raise ExtractionError("staging path must contain only real directories")
    if sys.platform.startswith("linux"):
        info = os.lstat(path)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ExtractionError("staging directory must be private and owned by the effective user")
    return path


def publish(source, target):
    """Atomically publish without replacement, or fail closed if unsupported."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            rename = libc.renameat2
        except AttributeError as error:
            raise ExtractionError("atomic no-replace publication is unavailable") from error
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
            code = ctypes.get_errno()
            if code in (errno.EEXIST, errno.ENOTEMPTY):
                raise ExtractionError("version already exists")
            raise ExtractionError("atomic no-replace publication failed")
    elif os.name == "nt":
        try:
            os.rename(source, target)
        except FileExistsError as error:
            raise ExtractionError("version already exists") from error
    else:
        raise ExtractionError("atomic no-replace publication is unavailable")


def open_output(root, name):
    target = root.joinpath(*name.split("/"))
    current = root
    for part in name.split("/")[:-1]:
        current = current / part
        try:
            current.mkdir(mode=0o700)
            if os.name == "posix":
                current.chmod(0o700)
        except FileExistsError:
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                raise ExtractionError("invalid output directory")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "wb")
    except BaseException:
        os.close(descriptor)
        raise


def verify_written(root, expected):
    """Check the actual written files, without retaining their contents in memory."""
    def check_entry(path, is_directory):
        info = os.lstat(path)
        if (getattr(info, "st_file_attributes", 0) & 0x400
                or (not stat.S_ISDIR(info.st_mode) if is_directory else not stat.S_ISREG(info.st_mode))):
            raise ExtractionError("unexpected output entry")
        if not is_directory and info.st_nlink != 1:
            raise ExtractionError("output file has unsafe links")
        if sys.platform.startswith("linux"):
            mode = 0o700 if is_directory else 0o600
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode:
                raise ExtractionError("output ownership or permissions are invalid")
        return info

    check_entry(root, True)
    expected_dirs = set()
    for name in expected:
        parts = name.split("/")[:-1]
        expected_dirs.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    actual_dirs = set()
    actual = {}
    def walk_error(error):
        raise error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs:
            path = Path(directory) / name
            check_entry(path, True)
            actual_dirs.add(path.relative_to(root).as_posix())
        for name in files:
            path = Path(directory) / name
            info = check_entry(path, False)
            relative = path.relative_to(root).as_posix()
            if relative not in expected or info.st_size != expected[relative][0]:
                raise ExtractionError("unexpected output file size or path")
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                while True:
                    block = stream.read(validator.CHUNK_SIZE)
                    if not block:
                        break
                    size += len(block)
                    if size > expected[relative][0] or size > validator.MAX_MEMBER_BYTES:
                        raise ExtractionError("output file exceeds its expected size")
                    digest.update(block)
            actual[relative] = (size, digest.hexdigest())
    if actual != expected or actual_dirs != expected_dirs:
        raise ExtractionError("written files do not match validated data")


def extract_artifact(artifact, revision, sha256, staging_dir):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise ExtractionError("extractor must not run as root")
    if not validator.SHA_RE.fullmatch(revision):
        raise ExtractionError("revision must be a 40-character lowercase hexadecimal SHA")
    if not validator.DIGEST_RE.fullmatch(sha256):
        raise ExtractionError("SHA256 must be a 64-character lowercase hexadecimal digest")
    staging = check_staging(staging_dir)
    snapshot, actual_digest = validator.snapshot_artifact(artifact, sha256)
    try:
        expected = {}
        count, total = validator.validate_snapshot(snapshot, revision, manifest=expected)
        with tempfile.TemporaryDirectory(prefix=".extract-", dir=staging) as temp:
            root = Path(temp)
            if os.name == "posix":
                root.chmod(0o700)
            snapshot.seek(0)
            written = {}
            second = validator.validate_snapshot(snapshot, revision, manifest=written,
                                                 output_factory=lambda name: open_output(root, name))
            if second != (count, total) or written != expected:
                raise ExtractionError("extracted data does not match validated data")
            verify_written(root, expected)
            target = staging / revision
            publish(root, target)
        return {"REVISION": revision, "SHA256": actual_digest, "FILE_COUNT": count,
                "TOTAL_BYTES": total, "STAGING_PATH": str(target)}
    finally:
        snapshot.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--staging-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = extract_artifact(args.artifact, args.revision, args.sha256, args.staging_dir)
    except (ExtractionError, validator.ValidationError, OSError):
        parser.exit(1, "Extraction failed: invalid artifact, staging path, or filesystem operation\n")
    print("EXTRACTION_OK")
    for key in ("REVISION", "SHA256", "FILE_COUNT", "TOTAL_BYTES", "STAGING_PATH"):
        print(f"{key}: {result[key]}")
    return 0


if __name__ == "__main__":
    main()
