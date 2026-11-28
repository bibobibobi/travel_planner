"""Bounded health-check primitives for the candidate deployment controller."""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

CHECKS = (
    ('http://127.0.0.1:5001/api/health', {'status': 'ok'}),
    ('http://127.0.0.1:5001/api/ready', {'status': 'ready', 'database': 'ok'}),
    ('https://bobo-travel-planner.duckdns.org/api/ready', {'status': 'ready', 'database': 'ok'}),
    ('https://bobo-travel-planner.duckdns.org/', None),
)
MAX_RESPONSE = 1024 * 1024
SERVICE = 'travel.service'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_response(opener, url, expected, timeout):
    with opener.open(url, timeout=timeout) as response:
        if response.status != 200:
            return False
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            return False
        if expected is None:
            return ('text/html' in response.headers.get('Content-Type', '').lower()
                    and b'<html' in body.lower())
        try:
            return json.loads(body) == expected
        except (ValueError, UnicodeDecodeError):
            return False


def healthy(*, total_timeout=45, attempts=3):
    deadline = time.monotonic() + total_timeout
    for attempt in range(attempts):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            service = subprocess.run(['/bin/systemctl', 'is-active', '--quiet', SERVICE],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, timeout=min(5, remaining), check=False)
            if service.returncode == 0:
                for index, _ in enumerate(CHECKS):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    # A separate process allows a hard deadline even when a
                    # peer keeps sending bytes just before socket timeouts.
                    result = subprocess.run(['/usr/bin/python3', '-I', '-B', __file__, '--probe', str(index)],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, timeout=min(5, remaining),
                                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, check=False)
                    if result.returncode != 0:
                        break
                else:
                    return True
        except (OSError, urllib.error.URLError, subprocess.SubprocessError):
            pass
        if attempt + 1 < attempts:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(2, remaining))
    return False


def main():
    if len(sys.argv) != 3 or sys.argv[1] != '--probe' or sys.argv[2] not in ('0', '1', '2', '3'):
        return 2
    url, expected = CHECKS[int(sys.argv[2])]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        return 0 if check_response(opener, url, expected, 5) else 1
    except (OSError, urllib.error.URLError):
        return 1


if __name__ == '__main__':
    sys.exit(main())
