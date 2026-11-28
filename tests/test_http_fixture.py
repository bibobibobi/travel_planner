import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux symlink fixture')
SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/server/integration_http_service.py'


@pytest.mark.parametrize(('behavior_file', 'app_behavior', 'expected'), [
    ('healthy', 'badhealth', 200),
    (None, 'badhealth', 503),
    (None, 'healthy', 200),
])
def test_behavior_file_and_artifact_fallback(tmp_path, behavior_file, app_behavior, expected):
    release = tmp_path / 'releases' / ('a' * 40)
    release.mkdir(parents=True)
    (release / 'app.py').write_text(app_behavior, encoding='ascii')
    if behavior_file is not None:
        (release / 'behavior').write_text(behavior_file, encoding='ascii')
    (tmp_path / 'current').symlink_to(release)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    process = subprocess.Popen([sys.executable, str(SCRIPT), str(tmp_path), str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                    status = response.status
                break
            except urllib.error.HTTPError as error:
                status = error.code
                break
            except urllib.error.URLError:
                if time.monotonic() >= deadline or process.poll() is not None:
                    raise
                time.sleep(0.05)
        assert status == expected
    finally:
        process.terminate()
        process.wait(timeout=5)
