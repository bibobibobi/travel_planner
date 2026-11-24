from werkzeug.security import check_password_hash

from app import User, db

INVITE_CODE = "test-invite-code"


def register(client, email="traveler@example.com", password="safe-password"):
    return client.post(
        "/api/register",
        json={
            "email": email,
            "password": password,
            "invite_code": INVITE_CODE,
        },
    )


def test_register_creates_a_user_with_a_hashed_password(client, app):
    response = register(client)

    assert response.status_code == 201
    assert response.get_json() == {"message": "註冊成功！"}

    with app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(email="traveler@example.com")
        ).scalar_one()

    assert user.password_hash != "safe-password"
    assert check_password_hash(user.password_hash, "safe-password")


def test_register_rejects_an_invalid_invite_code(client):
    response = client.post(
        "/api/register",
        json={
            "email": "traveler@example.com",
            "password": "safe-password",
            "invite_code": "invalid-code",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "無效的邀請碼"}


def test_login_returns_a_jwt_for_valid_credentials(client):
    register(client)

    response = client.post(
        "/api/login",
        json={"email": "traveler@example.com", "password": "safe-password"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["message"] == "登入成功！"
    assert isinstance(body["access_token"], str)
    assert body["access_token"]


def test_login_rejects_an_incorrect_password(client):
    register(client)

    response = client.post(
        "/api/login",
        json={"email": "traveler@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "帳號或密碼錯誤"}
