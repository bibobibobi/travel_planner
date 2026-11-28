#!/bin/bash
# Unprivileged stream tests in a newly-created native Linux directory.
set -euo pipefail
if (( $# != 1 )); then echo 'Usage: bash test-stream-linux.sh /path/to/repository' >&2; exit 2; fi
repo=$(realpath "$1")
base="$HOME/travel-deploy-test"
mkdir -p "$base"
work=$(mktemp -d "$base/stream.XXXXXXXX")
echo "Test directory: $work"
cp "$repo/deploy/server/artifact_stream.py" "$work/"
cd "$work"
python3 - <<'PY'
import hashlib
import io
import os
import artifact_stream as stream

revision = 'a' * 40
for data, limit, expected in [(b'hello', 10, True), (b'', 10, False), (b'hello', 4, False)]:
    r, w = os.pipe()
    os.write(w, data)
    os.close(w)
    try:
        try:
            size = stream.receive(r, io.BytesIO(), revision, hashlib.sha256(data).hexdigest(), max_bytes=limit)
            assert expected and size == len(data)
        except stream.ReceiveError:
            assert not expected
    finally:
        os.close(r)
r, w = os.pipe()
try:
    try:
        stream.receive(r, io.BytesIO(), revision, '0' * 64, timeout=0.05)
        raise AssertionError('timeout not enforced')
    except stream.ReceiveError:
        pass
finally:
    os.close(r)
    os.close(w)
print('STREAM_TEST_OK')
PY
echo 'Stream tests only; root snapshot and account integration remain unverified.'
echo "Inspect and remove this test directory manually: $work"
