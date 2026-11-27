from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from app import db


def test_api_root_returns_service_message(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"message": "API 伺服器運作中！"}


def test_liveness_returns_ok_without_database(client):
    with patch.object(db.session, 'execute', side_effect=AssertionError('database used')):
        response = client.get('/api/health')

    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok'}


def test_readiness_returns_ready_with_test_database(client):
    response = client.get('/api/ready')

    assert response.status_code == 200
    assert response.get_json() == {'status': 'ready', 'database': 'ok'}


def test_readiness_returns_safe_503_and_rolls_back_after_query_failure(client):
    error = OperationalError(
        'SELECT 1', {}, Exception('postgresql://db-user:super-secret@db.example/travel')
    )
    with (patch.object(db.session, 'execute', side_effect=error),
          patch.object(db.session, 'rollback') as rollback):
        response = client.get('/api/ready')

    assert response.status_code == 503
    assert response.get_json() == {'status': 'not_ready', 'database': 'unavailable'}
    assert 'super-secret' not in response.get_data(as_text=True)
    assert 'db.example' not in response.get_data(as_text=True)
    rollback.assert_called_once_with()


def test_health_endpoints_do_not_require_login(client):
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/ready').status_code == 200
