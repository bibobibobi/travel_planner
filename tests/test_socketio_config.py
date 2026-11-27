from unittest.mock import patch

import pytest

from app import create_app, socketio


def config(tmp_path, **overrides):
    return {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "UPLOAD_FOLDER": str(tmp_path),
        **overrides,
    }


def test_default_mode_is_threading(monkeypatch, tmp_path):
    monkeypatch.delenv("SOCKETIO_ASYNC_MODE", raising=False)
    app = create_app(config(tmp_path))
    assert app.config["SOCKETIO_ASYNC_MODE"] == "threading"
    assert socketio.async_mode == "threading"


def test_factory_override_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCKETIO_ASYNC_MODE", "invalid")
    app = create_app(config(tmp_path, SOCKETIO_ASYNC_MODE="threading"))
    assert app.config["SOCKETIO_ASYNC_MODE"] == "threading"


def test_environment_selects_gevent(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCKETIO_ASYNC_MODE", "gevent")
    with patch.object(socketio, "init_app") as initialize:
        app = create_app(config(tmp_path))
    assert app.config["SOCKETIO_ASYNC_MODE"] == "gevent"
    assert initialize.call_args.kwargs["async_mode"] == "gevent"


def test_invalid_mode_fails_clearly(tmp_path):
    with pytest.raises(ValueError, match="SOCKETIO_ASYNC_MODE"):
        create_app(config(tmp_path, SOCKETIO_ASYNC_MODE="invalid"))


def test_missing_mode_dependency_fails_clearly(tmp_path):
    with (
        patch.object(socketio, "init_app", side_effect=ValueError("missing driver")),
        pytest.raises(RuntimeError, match="gevent.*dependencies"),
    ):
        create_app(config(tmp_path, SOCKETIO_ASYNC_MODE="gevent"))
