"""Reject disallowed WebSocket origins before gevent-websocket sends HTTP 101."""

from geventwebsocket.gunicorn.workers import GeventWebSocketWorker
from geventwebsocket.handler import WebSocketHandler


class OriginCheckedWebSocketHandler(WebSocketHandler):
    def upgrade_websocket(self):
        origin = self.environ.get('HTTP_ORIGIN')
        if self.environ.get('HTTP_UPGRADE', '').lower() == 'websocket' and origin is not None:
            config = getattr(self.application, 'config', {})
            if origin not in config.get('ALLOWED_ORIGINS', ()):
                self.start_response('403 Forbidden', [('Content-Type', 'text/plain')])
                return [b'Forbidden']
        return super().upgrade_websocket()


class OriginCheckedGeventWorker(GeventWebSocketWorker):
    wsgi_handler = OriginCheckedWebSocketHandler
