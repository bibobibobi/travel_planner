INVITE_CODE = "test-invite-code"


def register_and_login(client, email):
    registration = client.post(
        "/api/register",
        json={
            "email": email,
            "password": "safe-password",
            "invite_code": INVITE_CODE,
        },
    )
    assert registration.status_code == 201

    login = client.post(
        "/api/login",
        json={"email": email, "password": "safe-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.get_json()['access_token']}"}


def create_trip(client, headers, title):
    return client.post(
        "/api/trips",
        headers=headers,
        json={
            "title": title,
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "budget": "12000",
        },
    )


def share_trip(client, owner_headers, recipient_headers, trip_id, role):
    share_response = client.post(
        "/api/trips/generate-share",
        headers=owner_headers,
        json={"trip_id": trip_id, "role": role},
    )
    assert share_response.status_code == 200

    accept_response = client.post(
        "/api/trips/accept-share",
        headers=recipient_headers,
        json={"share_token": share_response.get_json()["share_token"]},
    )
    assert accept_response.status_code == 200


def test_trips_endpoint_requires_a_jwt(client):
    response = client.get("/api/trips")

    assert response.status_code == 401


def test_user_cannot_see_another_users_owned_trip(client):
    first_user_headers = register_and_login(client, "first@example.com")
    second_user_headers = register_and_login(client, "second@example.com")
    create_response = create_trip(client, first_user_headers, "第一位使用者的行程")

    response = client.get("/api/trips", headers=second_user_headers)

    assert create_response.status_code == 201
    assert response.status_code == 200
    assert response.get_json() == []


def test_owner_can_update_a_trip(client):
    owner_headers = register_and_login(client, "owner@example.com")
    trip_id = create_trip(client, owner_headers, "原始名稱").get_json()["id"]

    response = client.put(
        f"/api/trips/{trip_id}",
        headers=owner_headers,
        json={"title": "更新後名稱"},
    )
    trips_response = client.get("/api/trips", headers=owner_headers)

    assert response.status_code == 200
    assert trips_response.get_json()[0]["title"] == "更新後名稱"


def test_unrelated_user_cannot_update_or_delete_a_trip(client):
    owner_headers = register_and_login(client, "owner@example.com")
    other_headers = register_and_login(client, "other@example.com")
    trip_id = create_trip(client, owner_headers, "私人行程").get_json()["id"]

    update_response = client.put(
        f"/api/trips/{trip_id}",
        headers=other_headers,
        json={"title": "不應更新成功"},
    )
    delete_response = client.delete(f"/api/trips/{trip_id}", headers=other_headers)
    owner_trips = client.get("/api/trips", headers=owner_headers).get_json()

    assert update_response.status_code == 403
    assert delete_response.status_code == 403
    assert owner_trips[0]["title"] == "私人行程"


def test_viewer_cannot_update_but_editor_can_update_a_shared_trip(client):
    owner_headers = register_and_login(client, "owner@example.com")
    viewer_headers = register_and_login(client, "viewer@example.com")
    editor_headers = register_and_login(client, "editor@example.com")
    trip_id = create_trip(client, owner_headers, "共享行程").get_json()["id"]
    share_trip(client, owner_headers, viewer_headers, trip_id, "viewer")
    share_trip(client, owner_headers, editor_headers, trip_id, "editor")

    viewer_response = client.put(
        f"/api/trips/{trip_id}",
        headers=viewer_headers,
        json={"title": "檢視者不應更新"},
    )
    editor_response = client.put(
        f"/api/trips/{trip_id}",
        headers=editor_headers,
        json={"title": "編輯者更新"},
    )
    owner_trips = client.get("/api/trips", headers=owner_headers).get_json()

    assert viewer_response.status_code == 403
    assert editor_response.status_code == 200
    assert owner_trips[0]["title"] == "編輯者更新"
