import os

import pytest

# Set these before importing app.py so its module-level app instance never
# connects to a developer's PostgreSQL database during a test run.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ALLOWED_ORIGINS"] = ""
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-with-32-bytes"
os.environ["SECRET_KEY"] = "test-flask-secret"
os.environ["INVITE_CODE"] = "test-invite-code"
os.environ["GEMINI_API_KEY"] = "test-gemini-api-key"
os.environ["FXRATES_API_KEY"] = "test-fx-rates-api-key"

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "JWT_SECRET_KEY": "test-jwt-secret-key-with-32-bytes",
            "SECRET_KEY": "test-flask-secret",
            "SOCKETIO_ASYNC_MODE": "threading",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
