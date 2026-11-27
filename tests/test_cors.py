import pytest
from flask_jwt_extended import create_access_token

from app import User, create_app, db, parse_allowed_origins, socketio


@pytest.fixture
def cors_app(tmp_path):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                      'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
                      'JWT_SECRET_KEY': 'test-jwt-secret-key-with-32-bytes',
                      'SOCKETIO_ASYNC_MODE': 'threading',
                      'ALLOWED_ORIGINS': ' http://localhost:5173, http://127.0.0.1:5173, http://localhost:5173 '})
    with app.app_context():
        db.create_all()
        db.session.add(User(email='cors@example.invalid', password_hash='unused'))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_origin_parser():
    assert parse_allowed_origins(None) == []
    assert parse_allowed_origins(' , ') == []
    assert parse_allowed_origins(' https://example.com, http://localhost:5173,https://example.com ') == [
        'https://example.com', 'http://localhost:5173']
    assert parse_allowed_origins(['http://[::1]:5173']) == ['http://[::1]:5173']


@pytest.mark.parametrize('origin', ['*', 'null', 'https://*.example.com', 'https://example.com/',
    'https://example.com/path', 'https://example.com?x=1', 'https://example.com#fragment',
    'https://user@example.com', 'https://example.com:', 'https://example.com:99999',
    'ftp://example.com', 'https://example.com.evil/path', 'http://[::1]evil', 'http://bad host'])
def test_invalid_config_rejected(origin, tmp_path):
    with pytest.raises(ValueError, match='ALLOWED_ORIGINS'):
        create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                    'UPLOAD_FOLDER': str(tmp_path), 'ALLOWED_ORIGINS': origin})


@pytest.mark.parametrize('origin', ['http://localhost:5173', 'http://127.0.0.1:5173'])
def test_allowed_rest_and_preflight(cors_app, origin):
    client = cors_app.test_client()
    response = client.get('/api/trips', headers={'Origin': origin})
    assert response.status_code == 401
    assert response.headers['Access-Control-Allow-Origin'] == origin
    assert 'Origin' in response.headers.get('Vary', '')
    assert 'Access-Control-Allow-Credentials' not in response.headers
    preflight = client.options('/api/trips', headers={'Origin': origin,
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization,content-type'})
    assert preflight.headers['Access-Control-Allow-Origin'] == origin
    assert 'authorization' in preflight.headers['Access-Control-Allow-Headers'].lower()
    assert 'content-type' in preflight.headers['Access-Control-Allow-Headers'].lower()
    with cors_app.app_context():
        user = User.query.filter_by(email='cors@example.invalid').one()
        token = create_access_token(identity=str(user.id))
    authorized = client.get('/api/trips', headers={'Origin': origin, 'Authorization': 'Bearer ' + token})
    assert authorized.status_code == 200
    assert authorized.headers['Access-Control-Allow-Origin'] == origin


@pytest.mark.parametrize('origin', ['http://localhost:5174', 'http://localhost.evil:5173',
                                     'http://127.0.0.2:5173', 'null'])
def test_disallowed_origin_no_cors_headers(cors_app, origin):
    response = cors_app.test_client().get('/api/trips', headers={'Origin': origin})
    assert response.status_code == 401
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_no_origin_has_no_cors_header(cors_app):
    response = cors_app.test_client().get('/api/trips')
    assert response.status_code == 401
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_origin_is_not_interpreted_as_regex(tmp_path):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                      'UPLOAD_FOLDER': str(tmp_path), 'ALLOWED_ORIGINS': 'https://a.example.com'})
    client = app.test_client()
    assert client.get('/', headers={'Origin': 'https://a.example.com'}).headers['Access-Control-Allow-Origin'] == 'https://a.example.com'
    assert 'Access-Control-Allow-Origin' not in client.get('/', headers={'Origin': 'https://aXexampleYcom'}).headers


def test_factory_override_and_invalid_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('ALLOWED_ORIGINS', '*')
    settings = {'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'UPLOAD_FOLDER': str(tmp_path)}
    with pytest.raises(ValueError, match='ALLOWED_ORIGINS'):
        create_app(settings)
    app = create_app({**settings, 'ALLOWED_ORIGINS': ['http://localhost:5173']})
    assert app.config['ALLOWED_ORIGINS'] == ['http://localhost:5173']


@pytest.mark.parametrize('origin,allowed', [('http://localhost:5173', True),
    ('http://127.0.0.1:5173', True), ('http://localhost.evil:5173', False),
    ('http://localhost:5174', False), ('null', False)])
def test_engineio_polling_origin(cors_app, origin, allowed):
    response = cors_app.test_client().get('/socket.io/?EIO=4&transport=polling', headers={'Origin': origin})
    assert response.status_code == (200 if allowed else 400)


def test_empty_origin_polling_rejected(cors_app):
    response = cors_app.test_client().get('/socket.io/?EIO=4&transport=polling', headers={'Origin': ''})
    assert response.status_code == 403


def test_missing_origins_deny_origin_but_not_no_origin(tmp_path):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                      'UPLOAD_FOLDER': str(tmp_path), 'ALLOWED_ORIGINS': None})
    client = app.test_client()
    assert client.get('/socket.io/?EIO=4&transport=polling', headers={'Origin': 'http://localhost:5173'}).status_code == 400
    assert client.get('/socket.io/?EIO=4&transport=polling').status_code == 200
    assert 'Access-Control-Allow-Origin' not in client.get('/', headers={'Origin': 'http://localhost:5173'}).headers


def test_socket_auth_and_room_policy(cors_app):
    with cors_app.app_context():
        user = User.query.filter_by(email='cors@example.invalid').one()
        token = create_access_token(identity=str(user.id))
    anonymous = socketio.test_client(cors_app, headers={'Origin': 'http://localhost:5173'})
    assert not anonymous.is_connected()
    authorized = socketio.test_client(cors_app, headers={'Origin': 'http://localhost:5173'}, auth={'token': token})
    try:
        assert authorized.is_connected()
        assert authorized.emit('join_trip', {'trip_id': 123}, callback=True) == {'ok': False, 'error': 'access_denied'}
    finally:
        if authorized.is_connected():
            authorized.disconnect()
