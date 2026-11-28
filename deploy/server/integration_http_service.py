#!/usr/bin/python3
"""Unprivileged test-only HTTP service; never runs release code."""
import http.server
import os
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
port = int(sys.argv[2])
revision = os.readlink(root / 'current').split('/')[-1]
behavior_file = root / 'current/behavior'
if not behavior_file.exists():
    behavior_file = root / 'current/app.py'
behavior = behavior_file.read_text(encoding='ascii').strip()
if behavior == 'startfail' or (root / 'block-old').exists() and behavior == 'healthy':
    sys.exit(1)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/slow':
            (root / 'runtime/slow-received').write_text('received\n', encoding='ascii')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b' ')
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if behavior == 'badhealth':
            status, body, content = 503, b'{"status":"bad"}', 'application/json'
        elif self.path == '/api/health':
            status, body, content = 200, b'{"status":"ok"}', 'application/json'
        elif self.path == '/api/ready':
            status, body, content = 200, b'{"status":"ready","database":"ok"}', 'application/json'
        else:
            status, body, content = 200, b'<html>test</html>', 'text/html'
        self.send_response(status)
        self.send_header('Content-Type', content)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
