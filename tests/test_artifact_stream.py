import hashlib
import io
import os
import sys

import pytest

from deploy.server import artifact_stream

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipe selectors required")
REV = "a" * 40


def receive(data, *, digest=None, revision=REV, limit=1024):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, data)
        os.close(write_fd)
        write_fd = None
        output = io.BytesIO()
        size = artifact_stream.receive(read_fd, output, revision,
                                       digest or hashlib.sha256(data).hexdigest(),
                                       max_bytes=limit)
        return size, output.getvalue()
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def test_valid_stream():
    assert receive(b"artifact") == (8, b"artifact")


@pytest.mark.parametrize("data,kwargs", [
    (b"", {}), (b"large", {"limit": 4}), (b"data", {"digest": "0" * 64}),
    (b"data", {"revision": "A" * 40}),
])
def test_invalid_stream(data, kwargs):
    with pytest.raises(artifact_stream.ReceiveError):
        receive(data, **kwargs)


def test_timeout():
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(artifact_stream.ReceiveError, match="timed out"):
            artifact_stream.receive(read_fd, io.BytesIO(), REV, "0" * 64, timeout=0.01)
    finally:
        os.close(read_fd)
        os.close(write_fd)
