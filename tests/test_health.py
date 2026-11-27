import os
from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app, db


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


@pytest.mark.parametrize(
    ('configured_timeout', 'expected_connect_timeout', 'expected_statement_timeout'),
    [
        ('5', 5, 5000),
        ('0.1', 1, 100),
        (5.5, 6, 5500),
        ('0.0001', 1, 1),
        ('30', 30, 30000),
    ],
)
def test_postgresql_timeout_options_use_valid_psycopg2_types(
    configured_timeout, expected_connect_timeout, expected_statement_timeout
):
    app = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'postgresql+psycopg2://user:password@localhost/test',
            'HEALTH_CHECK_TIMEOUT_SECONDS': configured_timeout,
        }
    )

    connect_timeout = app.config['SQLALCHEMY_ENGINE_OPTIONS']['connect_args']['connect_timeout']
    assert type(connect_timeout) is int
    assert connect_timeout == expected_connect_timeout
    assert app.config['HEALTH_CHECK_STATEMENT_TIMEOUT_MILLISECONDS'] == expected_statement_timeout


@pytest.mark.parametrize(
    'configured_timeout',
    [False, 0, '0', -1, '-0.1', 30.1, '31', 'NaN', 'inf', 'bad'],
)
def test_invalid_health_check_timeouts_are_rejected(configured_timeout):
    with pytest.raises(ValueError, match='HEALTH_CHECK_TIMEOUT_SECONDS'):
        create_app(
            {
                'TESTING': True,
                'SQLALCHEMY_DATABASE_URI': 'postgresql+psycopg2://user:password@localhost/test',
                'HEALTH_CHECK_TIMEOUT_SECONDS': configured_timeout,
            }
        )


def test_postgresql_readiness_integration():
    """Exercise /api/ready against a dedicated, real PostgreSQL test database."""
    database_url = os.environ.get('TEST_POSTGRES_DATABASE_URL')
    if not database_url:
        pytest.skip('TEST_POSTGRES_DATABASE_URL is not configured; PostgreSQL integration test skipped')

    app = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': database_url,
            'HEALTH_CHECK_TIMEOUT_SECONDS': '0.1',
        }
    )
    try:
        response = app.test_client().get('/api/ready')
        assert response.status_code == 200
        assert response.get_json() == {'status': 'ready', 'database': 'ok'}
    finally:
        with app.app_context():
            db.session.remove()
