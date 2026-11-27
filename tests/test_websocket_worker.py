import runpy
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def handler_class():
    class BaseHandler:
        def upgrade_websocket(self):
            return 'delegated'

    worker_module = types.ModuleType('geventwebsocket.gunicorn.workers')
    worker_module.GeventWebSocketWorker = type('Worker', (), {})
    handler_module = types.ModuleType('geventwebsocket.handler')
    handler_module.WebSocketHandler = BaseHandler
    modules = {'geventwebsocket': types.ModuleType('geventwebsocket'),
               'geventwebsocket.gunicorn': types.ModuleType('geventwebsocket.gunicorn'),
               'geventwebsocket.gunicorn.workers': worker_module,
               'geventwebsocket.handler': handler_module}
    with patch.dict(sys.modules, modules):
        namespace = runpy.run_path(str(Path(__file__).resolve().parent.parent / 'websocket_worker.py'))
    return namespace['OriginCheckedWebSocketHandler']


@pytest.mark.parametrize('origin,allowed', [
    (None, True), ('', False), ('null', False),
    ('http://localhost.evil:5173', False), ('http://localhost:5173', True),
])
def test_websocket_origin_header_values(handler_class, origin, allowed):
    handler = handler_class()
    handler.environ = {'HTTP_UPGRADE': 'websocket'}
    if origin is not None:
        handler.environ['HTTP_ORIGIN'] = origin
    handler.application = types.SimpleNamespace(config={'ALLOWED_ORIGINS': ['http://localhost:5173']})
    responses = []
    handler.start_response = lambda status, headers: responses.append((status, headers))
    result = handler.upgrade_websocket()
    if allowed:
        assert result == 'delegated'
        assert responses == []
    else:
        assert result == [b'Forbidden']
        assert responses[0][0] == '403 Forbidden'
