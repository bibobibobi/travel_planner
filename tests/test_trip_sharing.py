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


def create_trip(client, headers):
    response = client.post(
        "/api/trips",
        headers=headers,
        json={
            "title": "分享測試行程",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "budget": "12000",
        },
    )
    assert response.status_code == 201
    return response.get_json()["id"]


def generate_share_token(client, owner_headers, trip_id, role):
    response = client.post(
        "/api/trips/generate-share",
        headers=owner_headers,
        json={"trip_id": trip_id, "role": role},
    )
    assert response.status_code == 200
    return response.get_json()["share_token"]


def accept_share(client, headers, token):
    return client.post(
        "/api/trips/accept-share",
        headers=headers,
        json={"share_token": token},
    )


def test_recipient_can_accept_a_viewer_share_link(client):
    owner_headers = register_and_login(client, "owner@example.com")
    recipient_headers = register_and_login(client, "recipient@example.com")
    trip_id = create_trip(client, owner_headers)
    token = generate_share_token(client, owner_headers, trip_id, "viewer")

    accept_response = accept_share(client, recipient_headers, token)
    trips_response = client.get("/api/trips", headers=recipient_headers)

    assert accept_response.status_code == 200
    assert accept_response.get_json()["role"] == "viewer"
    assert trips_response.status_code == 200
    assert trips_response.get_json() == [
        {
            "id": trip_id,
            "title": "👥 分享測試行程",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "budget": 12000,
            "role": "viewer",
        }
    ]


def test_accepting_the_same_link_twice_is_idempotent(client):
    owner_headers = register_and_login(client, "owner@example.com")
    recipient_headers = register_and_login(client, "recipient@example.com")
    token = generate_share_token(client, owner_headers, create_trip(client, owner_headers), "viewer")

    first_response = accept_share(client, recipient_headers, token)
    second_response = accept_share(client, recipient_headers, token)
    trips_response = client.get("/api/trips", headers=recipient_headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.get_json()["role"] == "viewer"
    assert len(trips_response.get_json()) == 1


def test_a_new_share_link_can_upgrade_a_recipient_to_editor(client):
    owner_headers = register_and_login(client, "owner@example.com")
    recipient_headers = register_and_login(client, "recipient@example.com")
    trip_id = create_trip(client, owner_headers)
    viewer_token = generate_share_token(client, owner_headers, trip_id, "viewer")
    editor_token = generate_share_token(client, owner_headers, trip_id, "editor")

    accept_share(client, recipient_headers, viewer_token)
    upgrade_response = accept_share(client, recipient_headers, editor_token)
    trips_response = client.get("/api/trips", headers=recipient_headers)

    assert upgrade_response.status_code == 200
    assert upgrade_response.get_json()["role"] == "editor"
    assert trips_response.get_json()[0]["role"] == "editor"


def test_non_owner_and_invalid_tokens_are_rejected(client):
    owner_headers = register_and_login(client, "owner@example.com")
    other_headers = register_and_login(client, "other@example.com")
    trip_id = create_trip(client, owner_headers)

    generate_response = client.post(
        "/api/trips/generate-share",
        headers=other_headers,
        json={"trip_id": trip_id, "role": "viewer"},
    )
    accept_response = accept_share(client, other_headers, "not-a-valid-token")

    assert generate_response.status_code == 403
    assert accept_response.status_code == 400


def test_share_role_must_be_viewer_or_editor(client):
    owner_headers = register_and_login(client, "owner@example.com")
    trip_id = create_trip(client, owner_headers)

    response = client.post(
        "/api/trips/generate-share",
        headers=owner_headers,
        json={"trip_id": trip_id, "role": "administrator"},
    )

    assert response.status_code == 400
