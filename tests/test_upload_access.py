import io

INVITE_CODE = "test-invite-code"


def register_and_login(client, email):
    response = client.post(
        "/api/register",
        json={
            "email": email,
            "password": "safe-password",
            "invite_code": INVITE_CODE,
        },
    )
    assert response.status_code == 201
    response = client.post(
        "/api/login",
        json={"email": email, "password": "safe-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.get_json()['access_token']}"}


def create_trip(client, headers):
    response = client.post(
        "/api/trips",
        headers=headers,
        json={
            "title": "圖片授權測試",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "budget": "12000",
        },
    )
    assert response.status_code == 201
    return response.get_json()["id"]


def share_trip(client, owner_headers, recipient_headers, trip_id, role):
    response = client.post(
        "/api/trips/generate-share",
        headers=owner_headers,
        json={"trip_id": trip_id, "role": role},
    )
    assert response.status_code == 200
    response = client.post(
        "/api/trips/accept-share",
        headers=recipient_headers,
        json={"share_token": response.get_json()["share_token"]},
    )
    assert response.status_code == 200


def upload_trip_images(client, headers, trip_id, monkeypatch):
    monkeypatch.setattr("app.get_twd_rate", lambda _currency: 1.0)
    response = client.post(
        "/api/expenses",
        headers=headers,
        data={
            "trip_id": str(trip_id),
            "amount": "100",
            "currency": "TWD",
            "category": "food",
            "day_number": "1",
            "receipt_image": (io.BytesIO(b"test upload image"), "receipt.png"),
        },
    )
    assert response.status_code == 201
    response = client.get(f"/api/expenses?trip_id={trip_id}", headers=headers)
    assert response.status_code == 200
    expense_image_url = response.get_json()[0]["image_url"]

    response = client.post(
        "/api/shopping",
        headers=headers,
        data={
            "trip_id": str(trip_id),
            "name": "camera",
            "item_image": (io.BytesIO(b"test shopping image"), "camera.png"),
        },
    )
    assert response.status_code == 201
    response = client.get(f"/api/shopping?trip_id={trip_id}", headers=headers)
    assert response.status_code == 200
    return (expense_image_url, response.get_json()[0]["image_url"])


def test_uploaded_images_require_current_trip_access(client, monkeypatch):
    owner_headers = register_and_login(client, "owner@example.com")
    editor_headers = register_and_login(client, "editor@example.com")
    viewer_headers = register_and_login(client, "viewer@example.com")
    other_headers = register_and_login(client, "other@example.com")
    trip_id = create_trip(client, owner_headers)
    share_trip(client, owner_headers, editor_headers, trip_id, "editor")
    share_trip(client, owner_headers, viewer_headers, trip_id, "viewer")
    image_urls = upload_trip_images(client, owner_headers, trip_id, monkeypatch)

    for image_url, expected_data in zip(
        image_urls,
        (b"test upload image", b"test shopping image"),
        strict=True,
    ):
        assert client.get(image_url).status_code == 401
        assert client.get(image_url, headers=other_headers).status_code == 403

        for headers in (owner_headers, editor_headers, viewer_headers):
            response = client.get(image_url, headers=headers)
            assert response.status_code == 200
            assert response.data == expected_data
            assert response.cache_control.private is True
            assert response.cache_control.no_store is True

    revocation_response = client.delete(f"/api/trips/{trip_id}", headers=viewer_headers)
    assert revocation_response.status_code == 200
    for image_url in image_urls:
        assert client.get(image_url, headers=viewer_headers).status_code == 403


def test_uploaded_image_returns_not_found_when_no_database_record_exists(client):
    headers = register_and_login(client, "user@example.com")

    response = client.get("/api/uploads/missing-image.png", headers=headers)

    assert response.status_code == 404
