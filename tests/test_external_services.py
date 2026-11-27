import base64
import io
import json

import app as app_module

INVITE_CODE = "test-invite-code"
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/"
    "etBq4QAAAABJRU5ErkJggg=="
)


def register_and_login(client):
    registration = client.post(
        "/api/register",
        json={
            "email": "traveler@example.com",
            "password": "safe-password",
            "invite_code": INVITE_CODE,
        },
    )
    assert registration.status_code == 201

    login = client.post(
        "/api/login",
        json={"email": "traveler@example.com", "password": "safe-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.get_json()['access_token']}"}


def test_twd_rate_returns_one_without_calling_an_api_for_twd(monkeypatch):
    app_module.rate_cache.clear()

    def fail_if_called(_host):
        raise AssertionError("TWD should not call the exchange-rate API")

    monkeypatch.setattr(app_module.http.client, "HTTPSConnection", fail_if_called)

    assert app_module.get_twd_rate("TWD") == 1.0


def test_twd_rate_caches_a_successful_external_response(monkeypatch):
    app_module.rate_cache.clear()
    calls = []

    class FakeResponse:
        def read(self):
            return json.dumps({"success": True, "rates": {"TWD": 0.22}}).encode()

    class FakeConnection:
        def __init__(self, host):
            calls.append(host)

        def request(self, method, url):
            assert method == "GET"
            assert "base=JPY" in url

        def getresponse(self):
            return FakeResponse()

    monkeypatch.setattr(app_module.http.client, "HTTPSConnection", FakeConnection)

    assert app_module.get_twd_rate("JPY") == 0.22
    assert app_module.get_twd_rate("JPY") == 0.22
    assert calls == ["api.fxratesapi.com"]


def test_twd_rate_uses_fallback_when_the_external_api_fails(monkeypatch):
    app_module.rate_cache.clear()

    def raise_connection_error(_host):
        raise OSError("network unavailable")

    monkeypatch.setattr(
        app_module.http.client, "HTTPSConnection", raise_connection_error
    )

    assert app_module.get_twd_rate("USD") == 32.0


def test_receipt_scan_requires_a_jwt(client):
    response = client.post("/api/scan-receipt")

    assert response.status_code == 401


def test_receipt_scan_rejects_a_missing_image_after_authentication(client):
    response = client.post("/api/scan-receipt", headers=register_and_login(client))

    assert response.status_code == 400
    assert response.get_json() == {"error": "沒有圖片"}


def test_receipt_scan_returns_the_mocked_gemini_result(client, monkeypatch):
    expected_result = {
        "amount": "120",
        "category": "飲食",
        "date": "2026-01-01",
        "receipt_details": {"store_name": "測試店家", "items": []},
    }

    class FakeResponse:
        text = json.dumps(expected_result)

    class FakeModel:
        def generate_content(self, _content, generation_config):
            assert generation_config.response_mime_type == "application/json"
            return FakeResponse()

    monkeypatch.setattr(
        app_module.genai, "GenerativeModel", lambda _model_name: FakeModel()
    )
    response = client.post(
        "/api/scan-receipt",
        headers=register_and_login(client),
        data={"receipt_image": (io.BytesIO(ONE_PIXEL_PNG), "receipt.png")},
    )

    assert response.status_code == 200
    assert response.get_json() == expected_result
