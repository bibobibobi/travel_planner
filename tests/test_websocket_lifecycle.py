import threading
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask_jwt_extended import create_access_token
from test_websocket_rooms import call

from app import db, emit_trip_update, expire_socket, socketio

pytest_plugins = ('test_websocket_rooms',)


@pytest.mark.parametrize('role', ['viewer', 'editor'])
def test_exit_cleans_every_sid_and_preserves_other_memberships(app, client, room_setup, role):
    trip = room_setup['trip']
    sockets = room_setup['sockets']
    second = socketio.test_client(app, auth={'token': room_setup['tokens'][role]})
    try:
        for sock in (sockets[role], second, sockets['owner']):
            assert call(sock, 'join_trip', {'trip_id': trip})['ok']
        assert client.delete(f'/api/trips/{trip}', headers=room_setup['headers'][role]).status_code == 200
        for sock in (sockets[role], second):
            assert [item['name'] for item in sock.get_received()] == ['access_revoked']
            assert not call(sock, 'join_trip', {'trip_id': trip})['ok']
        assert client.post('/api/items', headers=room_setup['headers']['owner'], json={'trip_id': trip, 'content': 'test'}).status_code == 201
        assert len(sockets['owner'].get_received()) == 1
        assert sockets[role].get_received() == second.get_received() == []
    finally:
        if second.is_connected():
            second.disconnect()


def test_failed_transaction_does_not_remove_membership(client, room_setup):
    trip, viewer = room_setup['trip'], room_setup['sockets']['viewer']
    assert call(viewer, 'join_trip', {'trip_id': trip})['ok']
    with (patch.object(db.session, 'commit', side_effect=RuntimeError('test failure')),
          pytest.raises(RuntimeError)):
        client.delete(f'/api/trips/{trip}', headers=room_setup['headers']['viewer'])
    assert viewer.get_received() == []
    assert client.post('/api/items', headers=room_setup['headers']['owner'], json={'trip_id': trip, 'content': 'test'}).status_code == 201
    assert [item['name'] for item in viewer.get_received()] == ['itinerary_updated']


def test_notification_error_does_not_prevent_other_sid_cleanup(app, client, room_setup):
    trip = room_setup['trip']
    first = room_setup['sockets']['viewer']
    second = socketio.test_client(app, auth={'token': room_setup['tokens']['viewer']})
    try:
        for sock in (first, second):
            assert call(sock, 'join_trip', {'trip_id': trip})['ok']
        with patch.object(socketio, 'emit', side_effect=RuntimeError('notification failure')):
            assert client.delete(f'/api/trips/{trip}', headers=room_setup['headers']['viewer']).status_code == 200
        with app.app_context():
            emit_trip_update('itinerary_updated', {'action': 'test'}, trip)
        assert first.get_received() == []
        assert second.get_received() == []
    finally:
        if second.is_connected():
            second.disconnect()


def test_delete_cleans_members_and_leaves_other_trip(client, room_setup):
    trip, other_trip, sockets = room_setup['trip'], room_setup['other_trip'], room_setup['sockets']
    for name in ('owner', 'viewer'):
        assert call(sockets[name], 'join_trip', {'trip_id': trip})['ok']
    assert call(sockets['other'], 'join_trip', {'trip_id': other_trip})['ok']
    assert client.delete(f'/api/trips/{trip}', headers=room_setup['headers']['owner']).status_code == 200
    for name in ('owner', 'viewer'):
        assert [item['name'] for item in sockets[name].get_received()] == ['access_revoked']
        assert not call(sockets[name], 'join_trip', {'trip_id': trip})['ok']
        assert call(sockets[name], 'leave_trip', {'trip_id': trip})['ok']
    assert client.post('/api/items', headers=room_setup['headers']['other'], json={'trip_id': other_trip, 'content': 'test'}).status_code == 201
    assert len(sockets['other'].get_received()) == 1


def test_expiry_blocks_all_updates_without_client_action(app, room_setup):
    trip, owner, viewer = room_setup['trip'], room_setup['sockets']['owner'], room_setup['sockets']['viewer']
    for sock in (owner, viewer):
        assert call(sock, 'join_trip', {'trip_id': trip})['ok']
    registry = app.extensions['socket_auth_registry']
    with registry['lock']:
        sid = next(sid for sid, state in registry['sids'].items() if state['user_id'] != next(iter(registry['sids'].values()))['user_id'] and trip in state['trips'])
        registry['sids'][sid]['exp'] = time.time() - 1
    with app.app_context():
        for event in ('itinerary_updated', 'expenses_updated', 'shopping_updated'):
            emit_trip_update(event, {'action': 'test'}, trip)
    assert len(owner.get_received()) == 3
    assert viewer.get_received() == []
    assert call(viewer, 'join_trip', {'trip_id': trip}) == {'ok': False, 'error': 'unauthenticated'}
    expire_socket(app, sid)
    assert not viewer.is_connected()
    assert sid not in registry['sids']


def test_expiry_cleans_registry_when_transport_errors(app, room_setup):
    registry = app.extensions['socket_auth_registry']
    with registry['lock']:
        sid = next(iter(registry['sids']))
        registry['sids'][sid]['exp'] = time.time() - 1
    with (patch.object(socketio, 'emit', side_effect=RuntimeError('notification failure')),
          patch.object(socketio.server, 'disconnect', side_effect=RuntimeError('disconnect failure'))):
        expire_socket(app, sid)
    assert sid not in registry['sids']


def test_short_lived_sid_is_disconnected_without_client_event(app, room_setup):
    trip, owner = room_setup['trip'], room_setup['sockets']['owner']
    registry = app.extensions['socket_auth_registry']
    with registry['lock']:
        owner_id = next(state['user_id'] for state in registry['sids'].values() if state['trips'] == set())
    with app.app_context():
        short_token = create_access_token(identity=str(owner_id), expires_delta=timedelta(seconds=2))
    short = socketio.test_client(app, auth={'token': short_token})
    try:
        assert short.is_connected()
        assert call(short, 'join_trip', {'trip_id': trip})['ok']
        assert call(owner, 'join_trip', {'trip_id': trip})['ok']
        deadline = time.monotonic() + 5
        while short.is_connected() and time.monotonic() < deadline:
            threading.Event().wait(0.05)
        assert not short.is_connected()
        with app.app_context():
            emit_trip_update('itinerary_updated', {'action': 'test'}, trip)
        assert len(owner.get_received()) == 1
    finally:
        if short.is_connected():
            short.disconnect()


def test_other_trip_subscription_survives_exit(app, client, room_setup):
    trip, other = room_setup['trip'], room_setup['other_trip']
    headers, viewer = room_setup['headers'], room_setup['sockets']['viewer']
    link = client.post('/api/trips/generate-share', headers=headers['other'], json={'trip_id': other, 'role': 'viewer'}).json['share_token']
    assert client.post('/api/trips/accept-share', headers=headers['viewer'], json={'share_token': link}).status_code == 200
    for trip_id in (trip, other):
        assert call(viewer, 'join_trip', {'trip_id': trip_id})['ok']
    assert client.delete(f'/api/trips/{trip}', headers=headers['viewer']).status_code == 200
    assert [item['name'] for item in viewer.get_received()] == ['access_revoked']
    assert client.post('/api/items', headers=headers['other'], json={'trip_id': other, 'content': 'test'}).status_code == 201
    assert [item['name'] for item in viewer.get_received()] == ['itinerary_updated']


def test_broadcast_waits_for_permission_change(app, room_setup, monkeypatch):
    import app as app_module

    trip, viewer = room_setup['trip'], room_setup['sockets']['viewer']
    assert call(viewer, 'join_trip', {'trip_id': trip})['ok']
    entered, release = threading.Event(), threading.Event()
    original = app_module.cleanup_trip_members
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(app_module, 'cleanup_trip_members', blocked)
    def delete():
        with app.test_client() as client:
            assert client.delete(f'/api/trips/{trip}', headers=room_setup['headers']['viewer']).status_code == 200
    def emit():
        with app.app_context():
            emit_trip_update('itinerary_updated', {'action': 'test'}, trip)
    deleting = threading.Thread(target=delete)
    deleting.start()
    assert entered.wait(5)
    broadcasting = threading.Thread(target=emit)
    broadcasting.start()
    release.set()
    deleting.join(5)
    broadcasting.join(5)
    assert not deleting.is_alive() and not broadcasting.is_alive()
    assert [item['name'] for item in viewer.get_received()] == ['access_revoked']


def test_expiry_between_access_check_and_broadcast(app, room_setup, monkeypatch):
    import app as app_module

    trip, owner = room_setup['trip'], room_setup['sockets']['owner']
    assert call(owner, 'join_trip', {'trip_id': trip})['ok']
    registry = app.extensions['socket_auth_registry']
    with registry['lock']:
        state = next(state for state in registry['sids'].values() if trip in state['trips'])
        expires = state['exp']
    now = [expires - 1]
    monkeypatch.setattr(app_module, 'time', SimpleNamespace(time=lambda: now[0]))
    entered, release = threading.Event(), threading.Event()
    original = app_module.has_trip_access
    def blocked(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(app_module, 'has_trip_access', blocked)
    def emit():
        with app.app_context():
            emit_trip_update('itinerary_updated', {'action': 'test'}, trip)
    worker = threading.Thread(target=emit)
    worker.start()
    assert entered.wait(5)
    now[0] = expires
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert owner.get_received() == []


@pytest.mark.parametrize('delete_owner', [False, True])
def test_join_and_delete_serialize(app, room_setup, monkeypatch, delete_owner):
    import app as app_module

    trip = room_setup['trip']
    entered, release = threading.Event(), threading.Event()
    original = app_module.has_trip_access
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(app_module, 'has_trip_access', blocked)
    result = {}
    joining = threading.Thread(target=lambda: result.update(join=call(room_setup['sockets']['viewer'], 'join_trip', {'trip_id': trip})))
    def delete():
        with app.test_client() as client:
            name = 'owner' if delete_owner else 'viewer'
            result['delete'] = client.delete(f'/api/trips/{trip}', headers=room_setup['headers'][name]).status_code
    joining.start()
    assert entered.wait(5)
    deleting = threading.Thread(target=delete)
    deleting.start()
    release.set()
    joining.join(5)
    deleting.join(5)
    assert not joining.is_alive() and not deleting.is_alive()
    assert result == {'join': {'ok': True, 'trip_id': trip}, 'delete': 200}
    assert [item['name'] for item in room_setup['sockets']['viewer'].get_received()] == ['access_revoked']
    monkeypatch.setattr(app_module, 'has_trip_access', original)
    assert not call(room_setup['sockets']['viewer'], 'join_trip', {'trip_id': trip})['ok']
