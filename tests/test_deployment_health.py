import io
import subprocess
from email.message import Message
from types import SimpleNamespace

from deploy.server import deployment_health as health


class Response:
    def __init__(self, body, status=200, content_type='application/json'):
        self.body = io.BytesIO(body)
        self.status = status
        self.headers = Message()
        self.headers['Content-Type'] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.body.close()

    def read(self, amount):
        return self.body.read(amount)


class Opener:
    def __init__(self, response):
        self.response = response

    def open(self, url, timeout):
        return self.response


def test_health_requires_exact_response_and_status():
    expected = {'status': 'ok'}
    assert health.check_response(Opener(Response(b'{"status":"ok"}')), 'test', expected, 1)
    assert not health.check_response(Opener(Response(b'{"status":"wrong"}')), 'test', expected, 1)
    assert not health.check_response(Opener(Response(b'{"status":"ok"}', 302)), 'test', expected, 1)


def test_frontend_requires_html_and_success():
    assert health.check_response(Opener(Response(b'<html></html>', content_type='text/html')), 'test', None, 1)
    assert not health.check_response(Opener(Response(b'error', content_type='text/html')), 'test', None, 1)


def test_oversized_response_is_rejected():
    assert not health.check_response(Opener(Response(b'x' * (health.MAX_RESPONSE + 1))),
                                     'test', {'status': 'ok'}, 1)


def test_slow_probe_is_terminated_on_timeout(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == '/bin/systemctl':
            return SimpleNamespace(returncode=0)
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(health.subprocess, 'run', run)
    assert not health.healthy(total_timeout=1, attempts=1)
    assert calls[1][0][:4] == ['/usr/bin/python3', '-I', '-B', health.__file__]
    assert 0 < calls[1][1]['timeout'] <= 1
