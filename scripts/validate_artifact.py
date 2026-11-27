"""Validate a travel_plan deployment artifact without extracting or executing it.

This script deliberately validates bytes from a private, size-limited snapshot.
Validation does not reserve or protect the source pathname: a later deployment
must open and validate the artifact it is about to extract again.
"""

import argparse
import hashlib
import io
import os
import re
import stat
import tarfile
import tempfile
import zlib
from pathlib import PurePosixPath

MAX_COMPRESSED_BYTES = 10 * 1024 * 1024
MAX_CONTENT_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_MEMBERS = 1000
MAX_PATH_BYTES = 512
MAX_PATH_DEPTH = 16
# This also covers headers, PAX records and tar padding, not merely file sizes.
MAX_STREAM_BYTES = 60 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024
MAX_HEADERS = 2000
CHUNK_SIZE = 64 * 1024
REVISION_LIMIT = 128

REQUIRED = frozenset({
    "app.py", "websocket_worker.py", "requirements.txt", "requirements-prod.txt",
    "REVISION", "dist/index.html",
})
ROOT_FILES = REQUIRED - {"dist/index.html"}
STATIC_EXTENSIONS = frozenset({
    ".html", ".js", ".mjs", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".avif", ".ico", ".woff", ".woff2", ".ttf", ".otf",
})
FORBIDDEN_DIST_PARTS = frozenset({"node_modules", "venv", "uploads"})
WINDOWS_DEVICE = re.compile(r"^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?$", re.IGNORECASE)
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class ValidationError(ValueError):
    """A deliberately non-sensitive validation failure."""


def valid_path(name):
    """Accept portable relative UTF-8 names while preserving legal Unicode."""
    try:
        encoded = name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if not name or len(encoded) > MAX_PATH_BYTES or name.startswith("/") or "\\" in name:
        return False
    parts = name.split("/")
    if len(parts) > MAX_PATH_DEPTH or str(PurePosixPath(name)) != name:
        return False
    return all(
        part not in ("", ".", "..")
        and not part.endswith((" ", "."))
        and not WINDOWS_DEVICE.fullmatch(part)
        and not any(ord(char) < 32 or 127 <= ord(char) <= 159 or char in '<>:"|?*'
                    for char in part)
        for part in parts
    )


def allowed(name):
    if name in ROOT_FILES:
        return True
    parts = name.split("/")
    return (len(parts) >= 2 and parts[0] == "dist"
            and not any(part.startswith(".") or part.casefold() in FORBIDDEN_DIST_PARTS
                        for part in parts[1:])
            and PurePosixPath(name).suffix.lower() in STATIC_EXTENSIONS)


class PathRegistry:
    """Reject duplicate, case-insensitive, and file/directory component conflicts."""

    def __init__(self):
        self._paths = {}

    def add_file(self, name):
        if not valid_path(name):
            raise ValidationError("archive contains an unsafe path")
        parts = name.split("/")
        for index in range(len(parts)):
            current = "/".join(parts[:index + 1])
            is_directory = index < len(parts) - 1
            key = current.casefold()
            previous = self._paths.get(key)
            if previous is not None:
                if previous != (current, is_directory):
                    raise ValidationError("archive contains conflicting paths")
                if not is_directory:
                    raise ValidationError("archive contains a duplicate path")
            self._paths[key] = (current, is_directory)


class StrictGzipReader(io.RawIOBase):
    """A single-member gzip reader with a decompressed-byte ceiling."""

    def __init__(self, source):
        self.source = source
        self.decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self.pending = b""
        self.buffer = bytearray()
        self.finished = False
        self.total = 0

    def readable(self):
        return True

    def _append(self, data):
        self.total += len(data)
        if self.total > MAX_STREAM_BYTES:
            raise ValidationError("archive decompressed data exceeds the limit")
        self.buffer.extend(data)

    def _fill(self, wanted):
        while not self.finished and len(self.buffer) < wanted:
            if not self.pending:
                self.pending = self.source.read(CHUNK_SIZE)
                if not self.pending:
                    raise ValidationError("truncated gzip data")
            try:
                data = self.decompressor.decompress(self.pending, CHUNK_SIZE)
            except zlib.error as error:
                raise ValidationError("invalid gzip data") from error
            self.pending = self.decompressor.unconsumed_tail
            self._append(data)
            if self.decompressor.eof:
                if self.decompressor.unused_data or self.pending or self.source.read(1):
                    raise ValidationError("gzip data has unexpected trailing bytes")
                self.finished = True
            elif not data and not self.pending:
                # The next loop reads more compressed data.
                continue

    def readinto(self, target):
        self._fill(len(target))
        count = min(len(target), len(self.buffer))
        target[:count] = self.buffer[:count]
        del self.buffer[:count]
        return count

    def drain(self):
        nonzero = any(self.buffer)
        self.buffer.clear()
        while True:
            block = self.read(CHUNK_SIZE)
            if not block:
                return nonzero
            nonzero = nonzero or any(block)


def snapshot_artifact(path, expected_digest):
    """Open once, reject unsafe source types, and return (private snapshot, digest)."""
    try:
        initial = os.lstat(path)
    except OSError as error:
        raise ValidationError("cannot safely inspect artifact") from error
    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
        raise ValidationError("artifact source must be a non-linked regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise ValidationError("cannot safely open artifact") from error
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (not hasattr(os, "O_NOFOLLOW")
                    and (info.st_dev, info.st_ino) != (initial.st_dev, initial.st_ino))):
            raise ValidationError("artifact source must be a non-linked regular file")
        digest = hashlib.sha256()
        snapshot = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")  # noqa: SIM115
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                total = 0
                while True:
                    block = source.read(CHUNK_SIZE)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_COMPRESSED_BYTES:
                        raise ValidationError("artifact exceeds the compressed size limit")
                    digest.update(block)
                    snapshot.write(block)
            if total == 0:
                raise ValidationError("artifact is empty")
            actual = digest.hexdigest()
            if actual != expected_digest:
                raise ValidationError("artifact SHA256 does not match")
            snapshot.seek(0)
            return snapshot, actual
        except BaseException:
            snapshot.close()
            raise
    finally:
        os.close(descriptor)


def _read_member(tar, member, collect_revision, output=None):
    stream = tar.extractfile(member)
    if stream is None:
        raise ValidationError("archive member data is unavailable")
    total = 0
    revision = bytearray()
    digest = hashlib.sha256()
    while True:
        block = stream.read(CHUNK_SIZE)
        if not block:
            break
        total += len(block)
        digest.update(block)
        if output is not None and output.write(block) != len(block):
            raise OSError("short write")
        if total > MAX_MEMBER_BYTES:
            raise ValidationError("archive member exceeds the size limit")
        if collect_revision:
            if len(revision) + len(block) > REVISION_LIMIT:
                raise ValidationError("REVISION is too large")
            revision.extend(block)
    if total != member.size:
        raise ValidationError("truncated archive member")
    return (bytes(revision) if collect_revision else total), digest.hexdigest()


def _read_exact(reader, size):
    chunks = bytearray()
    while len(chunks) < size:
        block = reader.read(min(CHUNK_SIZE, size - len(chunks)))
        if not block:
            raise ValidationError("truncated tar data")
        chunks.extend(block)
    return bytes(chunks)


def _validate_pax(data):
    """Accept only fields emitted by tarfile PAX_FORMAT for release files."""
    fields = set()
    offset = 0
    while offset < len(data):
        space = data.find(b" ", offset)
        if space < 0 or space - offset > 8 or not data[offset:space].isdigit():
            raise ValidationError("invalid PAX metadata")
        length = int(data[offset:space])
        end = offset + length
        if length <= space - offset + 2 or end > len(data) or data[end - 1:end] != b"\n":
            raise ValidationError("invalid PAX metadata")
        record = data[space + 1:end - 1]
        key, separator, value = record.partition(b"=")
        if not separator or key not in (b"path", b"mtime") or key in fields or not value:
            raise ValidationError("unsupported PAX metadata")
        try:
            value.decode("utf-8", "strict")
        except UnicodeDecodeError as error:
            raise ValidationError("invalid PAX metadata") from error
        fields.add(key)
        offset = end


def validate_framing(snapshot):
    """Check physical headers, padding and end markers before tarfile parses PAX."""
    reader = StrictGzipReader(snapshot)
    headers = 0
    pax_pending = False
    try:
        while True:
            block = _read_exact(reader, 512)
            if block == bytes(512):
                if pax_pending or _read_exact(reader, 512) != bytes(512):
                    raise ValidationError("invalid tar end marker")
                while True:
                    tail = reader.read(CHUNK_SIZE)
                    if not tail:
                        break
                    if any(tail):
                        raise ValidationError("tar archive has unexpected trailing data")
                if reader.total % 512:
                    raise ValidationError("invalid tar padding")
                return
            headers += 1
            if headers > MAX_HEADERS:
                raise ValidationError("archive has too many headers")
            try:
                member = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
            except (tarfile.HeaderError, UnicodeError, ValueError) as error:
                raise ValidationError("invalid tar header") from error
            size_field = block[124:136].strip(b" \0")
            if not size_field or any(c not in b"01234567" for c in size_field):
                raise ValidationError("invalid tar member size")
            size = int(size_field, 8)
            if member.type == tarfile.XHDTYPE:
                if pax_pending or size > MAX_METADATA_BYTES:
                    raise ValidationError("PAX metadata exceeds the limit or is repeated")
                _validate_pax(_read_exact(reader, size))
                pax_pending = True
            elif member.type in (tarfile.REGTYPE, tarfile.AREGTYPE):
                if size > MAX_MEMBER_BYTES:
                    raise ValidationError("archive member exceeds the size limit")
                remaining = size
                while remaining:
                    chunk = min(remaining, CHUNK_SIZE)
                    _read_exact(reader, chunk)
                    remaining -= chunk
                pax_pending = False
            else:
                raise ValidationError("archive contains a non-regular or sparse member")
            padding = (-size) % 512
            if padding and any(_read_exact(reader, padding)):
                raise ValidationError("invalid tar padding")
    except (OSError, EOFError) as error:
        raise ValidationError("invalid or truncated tar archive") from error


def validate_snapshot(snapshot, revision, manifest=None, output_factory=None):
    validate_framing(snapshot)
    snapshot.seek(0)
    registry = PathRegistry()
    seen = set()
    contents = 0
    sizes = {}
    javascript = False
    revision_bytes = None
    reader = StrictGzipReader(snapshot)
    try:
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                if len(seen) >= MAX_MEMBERS:
                    raise ValidationError("archive has too many members")
                if not member.isreg() or getattr(member, "issparse", lambda: False)():
                    raise ValidationError("archive contains a non-regular or sparse member")
                registry.add_file(member.name)
                if not allowed(member.name):
                    raise ValidationError("archive contains a forbidden member")
                if member.size > MAX_MEMBER_BYTES:
                    raise ValidationError("archive member exceeds the size limit")
                contents += member.size
                if contents > MAX_CONTENT_BYTES:
                    raise ValidationError("archive content exceeds the size limit")
                if output_factory is None:
                    data, digest = _read_member(archive, member, member.name == "REVISION")
                else:
                    with output_factory(member.name) as output:
                        data, digest = _read_member(archive, member, member.name == "REVISION", output)
                if manifest is not None:
                    manifest[member.name] = (member.size, digest)
                sizes[member.name] = member.size
                if member.name == "REVISION":
                    revision_bytes = data
                if member.name.startswith("dist/") and member.name.endswith(".js") and data:
                    javascript = True
                seen.add(member.name)
        if reader.drain():
            raise ValidationError("tar archive has unexpected trailing data")
    except (tarfile.TarError, EOFError, OSError) as error:
        raise ValidationError("invalid or truncated tar archive") from error
    if not REQUIRED <= seen:
        raise ValidationError("archive is missing a required file")
    if any(sizes[name] == 0 for name in REQUIRED):
        raise ValidationError("archive contains an empty required file")
    if not javascript:
        raise ValidationError("archive is missing JavaScript build output")
    if revision_bytes != (revision + "\n").encode("ascii"):
        raise ValidationError("REVISION does not match the requested commit")
    # Required files were counted above; inspect their non-emptiness without retaining them.
    # A second name-only pass is avoided: size was authenticated by the same tar stream.
    # These names have all been seen and member sizes are retained in this small mapping.
    return len(seen), contents


def validate_artifact(path, revision, digest):
    if not SHA_RE.fullmatch(revision):
        raise ValidationError("revision must be a 40-character lowercase hexadecimal SHA")
    if not DIGEST_RE.fullmatch(digest):
        raise ValidationError("SHA256 must be a 64-character lowercase hexadecimal digest")
    snapshot, actual = snapshot_artifact(path, digest)
    try:
        count, total = validate_snapshot(snapshot, revision)
    finally:
        snapshot.close()
    return {"REVISION": revision, "SHA256": actual, "FILE_COUNT": count, "TOTAL_BYTES": total}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_artifact(args.artifact, args.revision, args.sha256)
    except (ValidationError, OSError) as error:
        parser.exit(1, f"Validation failed: {error}\n")
    print("VALIDATION_OK")
    for key in ("REVISION", "SHA256", "FILE_COUNT", "TOTAL_BYTES"):
        print(f"{key}: {result[key]}")
    return 0


if __name__ == "__main__":
    main()
