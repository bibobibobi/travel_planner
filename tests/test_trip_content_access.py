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
            "title": "權限測試行程",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "budget": "12000",
        },
    )
    assert response.status_code == 201
    return response.get_json()["id"]


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


def create_trip_content(client, headers, trip_id, monkeypatch):
    item_response = client.post(
        "/api/items",
        headers=headers,
        json={
            "trip_id": trip_id,
            "content": "測試景點",
            "day_number": 1,
            "order_index": 0,
        },
    )
    assert item_response.status_code == 201

    monkeypatch.setattr("app.get_twd_rate", lambda _currency: 1.0)
    expense_response = client.post(
        "/api/expenses",
        headers=headers,
        data={
            "trip_id": trip_id,
            "amount": "100",
            "currency": "TWD",
            "category": "飲食",
            "day_number": "1",
        },
    )
    assert expense_response.status_code == 201

    shopping_response = client.post(
        "/api/shopping",
        headers=headers,
        data={"trip_id": trip_id, "name": "測試商品"},
    )
    assert shopping_response.status_code == 201

    return {
        "item_id": item_response.get_json()["id"],
        "expense_id": client.get(
            f"/api/expenses?trip_id={trip_id}", headers=headers
        ).get_json()[0]["id"],
        "shopping_id": shopping_response.get_json()["id"],
    }


def test_trip_content_endpoints_require_a_jwt(client):
    endpoints = [
        "/api/items?trip_id=1",
        "/api/expenses?trip_id=1",
        "/api/shopping?trip_id=1",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 401


def test_unrelated_user_cannot_read_trip_content(client, monkeypatch):
    owner_headers = register_and_login(client, "owner@example.com")
    other_headers = register_and_login(client, "other@example.com")
    trip_id = create_trip(client, owner_headers)
    create_trip_content(client, owner_headers, trip_id, monkeypatch)

    for endpoint in ("items", "expenses", "shopping"):
        response = client.get(
            f"/api/{endpoint}?trip_id={trip_id}", headers=other_headers
        )
        assert response.status_code == 403


def test_viewer_can_read_but_cannot_modify_trip_content(client, monkeypatch):
    owner_headers = register_and_login(client, "owner@example.com")
    viewer_headers = register_and_login(client, "viewer@example.com")
    trip_id = create_trip(client, owner_headers)
    content_ids = create_trip_content(client, owner_headers, trip_id, monkeypatch)
    share_trip(client, owner_headers, viewer_headers, trip_id, "viewer")

    for endpoint in ("items", "expenses", "shopping"):
        response = client.get(
            f"/api/{endpoint}?trip_id={trip_id}", headers=viewer_headers
        )
        assert response.status_code == 200
        assert len(response.get_json()) == 1

    responses = [
        client.put(
            f"/api/items/{content_ids['item_id']}",
            headers=viewer_headers,
            json={"content": "viewer 不可修改"},
        ),
        client.put(
            f"/api/expenses/{content_ids['expense_id']}",
            headers=viewer_headers,
            json={"amount": 200},
        ),
        client.put(
            f"/api/shopping/{content_ids['shopping_id']}",
            headers=viewer_headers,
            json={"is_bought": True},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]


def test_editor_can_create_trip_content(client, monkeypatch):
    owner_headers = register_and_login(client, "owner@example.com")
    editor_headers = register_and_login(client, "editor@example.com")
    trip_id = create_trip(client, owner_headers)
    share_trip(client, owner_headers, editor_headers, trip_id, "editor")
    monkeypatch.setattr("app.get_twd_rate", lambda _currency: 1.0)

    item_response = client.post(
        "/api/items",
        headers=editor_headers,
        json={"trip_id": trip_id, "content": "編輯者景點"},
    )
    expense_response = client.post(
        "/api/expenses",
        headers=editor_headers,
        data={
            "trip_id": trip_id,
            "amount": "100",
            "currency": "TWD",
            "category": "飲食",
        },
    )
    shopping_response = client.post(
        "/api/shopping",
        headers=editor_headers,
        data={"trip_id": trip_id, "name": "編輯者商品"},
    )

    assert [response.status_code for response in (item_response, expense_response, shopping_response)] == [
        201,
        201,
        201,
    ]
