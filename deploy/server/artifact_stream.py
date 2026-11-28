"""Bounded, timed artifact stream reception. This is not a deployment entrypoint."""

import hashlib
import os
import re
import selectors
import time

MAX_BYTES = 10 * 1024 * 1024
REVISION = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ReceiveError(ValueError):
    """A stream is invalid or cannot be accepted within its limits."""


def receive(source_fd, destination, revision, expected_digest, *, timeout=120,
            max_bytes=MAX_BYTES):
    """Copy a stream into an already-open private file and check its digest.

    The caller owns the output file, its permissions, cleanup and publication.
    This function does not establish trust in the caller or the input descriptor.
    """
    if not REVISION.fullmatch(revision) or not DIGEST.fullmatch(expected_digest):
        raise ReceiveError("invalid revision or digest")
    deadline = time.monotonic() + timeout
    digest = hashlib.sha256()
    size = 0
    with selectors.DefaultSelector() as selector:
        selector.register(source_fd, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise ReceiveError("upload timed out")
            chunk = os.read(source_fd, min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ReceiveError("artifact too large")
            destination.write(chunk)
            digest.update(chunk)
    if not size:
        raise ReceiveError("empty artifact")
    if digest.hexdigest() != expected_digest:
        raise ReceiveError("SHA256 mismatch")
    return size
