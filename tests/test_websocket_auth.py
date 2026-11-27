from datetime import timedelta
from unittest.mock import patch

import jwt as pyjwt
import pytest
from flask import current_app, request
from flask_jwt_extended import create_access_token, create_refresh_token

from app import User, create_app, db, socketio


@pytest.fixture
def user(app):
    with app.app_context():
        user = User(email='socket@example.invalid', password_hash='unused')
        db.session.add(user)
        db.session.commit()
        return user.id


def token(app, identity, **kwargs):
    with app.app_context():
        return create_access_token(identity=identity, **kwargs)


def assert_rejected(app, auth=None, **kwargs):
    client = socketio.test_client(app, auth=auth, **kwargs)
    try:
        assert not client.is_connected()
        assert not app.extensions['socket_auth_registry']['sids']
    finally:
        if client.is_connected():
            client.disconnect()


@pytest.mark.parametrize('case', [
    'no_auth', 'no_token', 'auth_list', 'token_number', 'malformed',
    'wrong_signature', 'expired', 'refresh', 'missing_user',
    'identity_number', 'identity_negative', 'identity_text', 'query_only',
])
def test_invalid_connections(app, user, case):
    with app.app_context():
        refresh = create_refresh_token(identity=str(user))
    cases = {
        'no_auth': None,
        'no_token': {},
        'auth_list': ['unexpected'],
        'token_number': {'token': 123},
        'malformed': {'token': 'invalid'},
        'wrong_signature': {'token': pyjwt.encode({'sub': str(user)}, 'different-test-signing-key-32-bytes', algorithm='HS256')},
        'expired': {'token': token(app, str(user), expires_delta=timedelta(seconds=-1))},
        'refresh': {'token': refresh},
        'missing_user': {'token': token(app, '999999')},
        'identity_number': {'token': token(app, user)},
        'identity_negative': {'token': token(app, '-1')},
        'identity_text': {'token': token(app, 'invalid')},
        'query_only': None,
    }
    query = {'query_string': 'token=' + token(app, str(user))} if case == 'query_only' else {}
    assert_rejected(app, cases[case], **query)


def test_sid_identity_and_cleanup(app, user):
    auth = {'token': token(app, str(user)), 'user_id': 999999}
    first = socketio.test_client(app, auth=auth)
    second = socketio.test_client(app, auth=auth)
    try:
        registry = app.extensions['socket_auth_registry']['sids']
        assert first.is_connected() and second.is_connected()
        assert len(registry) == 2
        assert all(entry['user_id'] == user and isinstance(entry['exp'], int) for entry in registry.values())
        first.disconnect()
        assert len(registry) == 1 and second.is_connected()
        second.disconnect()
        assert not registry
    finally:
        for client in (first, second):
            if client.is_connected():
                client.disconnect()


def test_database_failure_rejects_connection(app, user):
    access = token(app, str(user))
    with patch.object(db.session, 'get', side_effect=RuntimeError('database error')):
        assert_rejected(app, {'token': access})
    with app.app_context():
        assert db.session.get(User, user) is not None


@pytest.mark.parametrize('callback', ['_token_in_blocklist_callback', '_token_verification_callback'])
def test_jwt_policy_callbacks_are_enforced(app, user, monkeypatch, callback):
    access = token(app, str(user))
    manager = app.extensions['flask-jwt-extended']
    # A revoked token returns True; a failed custom verification returns False.
    monkeypatch.setattr(manager, callback, lambda _header, _claims: callback == '_token_in_blocklist_callback')
    assert_rejected(app, {'token': access})


def test_registry_isolation_between_apps(app, user, tmp_path):
    access = token(app, str(user))
    first = socketio.test_client(app, auth={'token': access})
    try:
        assert first.is_connected()
        first.disconnect()
        other = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                            'UPLOAD_FOLDER': str(tmp_path / 'other'),
                            'JWT_SECRET_KEY': 'test-jwt-secret-key-with-32-bytes',
                            'SOCKETIO_ASYNC_MODE': 'threading'})
        assert other.extensions['socket_auth_registry'] is not app.extensions['socket_auth_registry']
        assert not other.extensions['socket_auth_registry']['sids']
        with other.app_context():
            db.create_all()
            db.session.add(User(id=user, email='other@example.invalid', password_hash='unused'))
            db.session.commit()
        second = socketio.test_client(other, auth={'token': access})
        try:
            assert second.is_connected()
            assert len(other.extensions['socket_auth_registry']['sids']) == 1
            assert not app.extensions['socket_auth_registry']['sids']
        finally:
            if second.is_connected():
                second.disconnect()
            with other.app_context():
                db.session.remove()
                db.drop_all()
    finally:
        if first.is_connected():
            first.disconnect()


def test_request_context_restored_and_sid_stored(app, user, monkeypatch):
    access = token(app, str(user))
    original = db.session.get
    seen = []

    def check_context(*args, **kwargs):
        seen.append((current_app._get_current_object(), request.path))
        return original(*args, **kwargs)

    monkeypatch.setattr(db.session, 'get', check_context)
    client = socketio.test_client(app, auth={'token': access})
    try:
        assert client.is_connected()
        assert seen == [(app, '/')]
        assert len(app.extensions['socket_auth_registry']['sids']) == 1
    finally:
        if client.is_connected():
            client.disconnect()
