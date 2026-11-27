import pytest
from flask_jwt_extended import create_access_token

from app import User, db, socketio


@pytest.fixture
def room_setup(app, client):
    with app.app_context():
        users = [User(email=f'{name}@example.invalid', password_hash='unused')
                 for name in ('owner', 'editor', 'viewer', 'other')]
        db.session.add_all(users)
        db.session.commit()
        tokens = {name: create_access_token(identity=str(user.id))
                  for name, user in zip(('owner', 'editor', 'viewer', 'other'), users, strict=True)}
    headers = {name: {'Authorization': 'Bearer ' + token} for name, token in tokens.items()}
    def make_trip(owner):
        response = client.post('/api/trips', headers=headers[owner], json={
            'title': 'test', 'start_date': '2026-01-01', 'end_date': '2026-01-02'})
        assert response.status_code == 201
        return response.json['id']
    trip = make_trip('owner')
    other_trip = make_trip('other')
    for name in ('editor', 'viewer'):
        response = client.post('/api/trips/generate-share', headers=headers['owner'],
                               json={'trip_id': trip, 'role': name})
        response = client.post('/api/trips/accept-share', headers=headers[name],
                               json={'share_token': response.json['share_token']})
        assert response.status_code == 200
    sockets = {name: socketio.test_client(app, auth={'token': access}) for name, access in tokens.items()}
    yield {'trip': trip, 'other_trip': other_trip, 'headers': headers, 'tokens': tokens, 'sockets': sockets}
    for sock in sockets.values():
        if sock.is_connected():
            sock.disconnect()


def call(sock, event, payload):
    return sock.emit(event, payload, callback=True)


def test_roles_and_no_enumeration(room_setup):
    trip, sockets = room_setup['trip'], room_setup['sockets']
    for name in ('owner', 'editor', 'viewer'):
        assert call(sockets[name], 'join_trip', {'trip_id': trip}) == {'ok': True, 'trip_id': trip}
    denied = call(sockets['other'], 'join_trip', {'trip_id': trip, 'user_id': 1, 'role': 'owner'})
    missing = call(sockets['other'], 'join_trip', {'trip_id': 999999})
    assert denied == missing == {'ok': False, 'error': 'access_denied'}


@pytest.mark.parametrize('payload', [None, [], '1', {}, {'trip_id': None}, {'trip_id': True},
    {'trip_id': 1.0}, {'trip_id': 0}, {'trip_id': -1}, {'trip_id': 2147483648},
    {'trip_id': '2147483648'}, {'trip_id': ' 1'}, {'trip_id': '-1'}, {'trip_id': '1.0'},
    {'trip_id': '１２'}, {'trip_id': 'x'}, {'trip_id': '9' * 1000}])
def test_invalid_payloads(room_setup, payload):
    sock = room_setup['sockets']['owner']
    for event in ('join_trip', 'leave_trip'):
        assert call(sock, event, payload) == {'ok': False, 'error': 'invalid_trip_id'}


def test_database_error_is_closed(room_setup, monkeypatch):
    monkeypatch.setattr('app.has_trip_access', lambda *_args: (_ for _ in ()).throw(RuntimeError()))
    sock, trip = room_setup['sockets']['owner'], room_setup['trip']
    assert call(sock, 'join_trip', {'trip_id': trip}) == {'ok': False, 'error': 'access_denied'}
    socketio.emit('itinerary_updated', {'action': 'test'}, room=f'trip_{trip}')
    assert sock.get_received() == []


def test_events_isolated_and_leave_idempotent(room_setup, client, monkeypatch):
    trip, other_trip = room_setup['trip'], room_setup['other_trip']
    sockets, headers = room_setup['sockets'], room_setup['headers']
    for name in ('owner', 'viewer'):
        assert call(sockets[name], 'join_trip', {'trip_id': trip})['ok']
    assert call(sockets['owner'], 'join_trip', {'trip_id': str(trip)})['ok']
    assert call(sockets['other'], 'join_trip', {'trip_id': other_trip})['ok']
    assert not call(sockets['other'], 'join_trip', {'trip_id': trip})['ok']
    assert not call(sockets['editor'], 'join_trip', {'trip_id': other_trip})['ok']
    monkeypatch.setattr('app.get_twd_rate', lambda _currency: 1.0)
    assert client.post('/api/items', headers=headers['owner'], json={'trip_id': trip, 'content': 'item'}).status_code == 201
    assert client.post('/api/expenses', headers=headers['owner'], data={'trip_id': trip, 'amount': '10', 'currency': 'TWD', 'category': 'test'}).status_code == 201
    assert client.post('/api/shopping', headers=headers['owner'], data={'trip_id': trip, 'name': 'test'}).status_code == 201
    for name in ('owner', 'viewer'):
        assert [event['name'] for event in sockets[name].get_received()] == [
            'itinerary_updated', 'expenses_updated', 'shopping_updated']
    assert sockets['other'].get_received() == []
    assert sockets['editor'].get_received() == []
    assert client.post('/api/items', headers=headers['other'], json={'trip_id': other_trip, 'content': 'other'}).status_code == 201
    assert len(sockets['other'].get_received()) == 1
    assert sockets['owner'].get_received() == []
    assert sockets['viewer'].get_received() == []
    for _ in range(2):
        assert call(sockets['viewer'], 'leave_trip', {'trip_id': trip}) == {'ok': True, 'trip_id': trip}
    assert client.post('/api/items', headers=headers['owner'], json={'trip_id': trip, 'content': 'second'}).status_code == 201
    assert len(sockets['owner'].get_received()) == 1
    assert sockets['viewer'].get_received() == []


def test_leave_after_access_loss_and_independent_sid(app, client, room_setup):
    trip, headers, sockets = room_setup['trip'], room_setup['headers'], room_setup['sockets']
    second = socketio.test_client(app, auth={'token': room_setup['tokens']['viewer']})
    try:
        for sock in (sockets['viewer'], second):
            assert call(sock, 'join_trip', {'trip_id': trip})['ok']
        assert client.delete(f'/api/trips/{trip}', headers=headers['viewer']).status_code == 200
        for sock in (sockets['viewer'], second):
            assert [event['name'] for event in sock.get_received()] == ['access_revoked']
        assert call(sockets['viewer'], 'leave_trip', {'trip_id': trip})['ok']
        assert client.post('/api/items', headers=headers['owner'], json={'trip_id': trip, 'content': 'test'}).status_code == 201
        assert sockets['viewer'].get_received() == []
        assert second.get_received() == []
        second.disconnect()
        second = socketio.test_client(app, auth={'token': room_setup['tokens']['viewer']})
        assert call(second, 'join_trip', {'trip_id': trip}) == {'ok': False, 'error': 'access_denied'}
    finally:
        if second.is_connected():
            second.disconnect()
