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


def create_trip(client, headers, title="排序測試行程"):
    response = client.post(
        "/api/trips",
        headers=headers,
        json={
            "title": title,
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "budget": "12000",
        },
    )
    assert response.status_code == 201
    return response.get_json()["id"]


def create_item(client, headers, trip_id, content, day_number, order_index):
    response = client.post(
        "/api/items",
        headers=headers,
        json={
            "trip_id": trip_id,
            "content": content,
            "day_number": day_number,
            "order_index": order_index,
        },
    )
    assert response.status_code == 201
    return response.get_json()["id"]


def get_items_by_id(client, headers, trip_id):
    response = client.get(f"/api/items?trip_id={trip_id}", headers=headers)
    assert response.status_code == 200
    return {item["id"]: item for item in response.get_json()}


def test_owner_can_reorder_items_within_a_day(client):
    owner_headers = register_and_login(client, "owner@example.com")
    trip_id = create_trip(client, owner_headers)
    first_id = create_item(client, owner_headers, trip_id, "第一站", 1, 0)
    second_id = create_item(client, owner_headers, trip_id, "第二站", 1, 1)
    third_id = create_item(client, owner_headers, trip_id, "第三站", 1, 2)

    response = client.put(
        "/api/items/reorder",
        headers=owner_headers,
        json={
            "reordered_items": [
                {"id": third_id, "order_index": 0, "day_number": 1},
                {"id": first_id, "order_index": 1, "day_number": 1},
                {"id": second_id, "order_index": 2, "day_number": 1},
            ]
        },
    )
    items = client.get(f"/api/items?trip_id={trip_id}", headers=owner_headers).get_json()

    assert response.status_code == 200
    assert [item["id"] for item in items] == [third_id, first_id, second_id]


def test_owner_can_move_an_item_between_days(client):
    owner_headers = register_and_login(client, "owner@example.com")
    trip_id = create_trip(client, owner_headers)
    first_id = create_item(client, owner_headers, trip_id, "第一天景點", 1, 0)
    second_id = create_item(client, owner_headers, trip_id, "第一天餐廳", 1, 1)
    third_id = create_item(client, owner_headers, trip_id, "第二天景點", 2, 0)

    response = client.put(
        "/api/items/reorder",
        headers=owner_headers,
        json={
            "reordered_items": [
                {"id": second_id, "order_index": 0, "day_number": 1},
                {"id": third_id, "order_index": 0, "day_number": 2},
                {"id": first_id, "order_index": 1, "day_number": 2},
            ]
        },
    )
    items = get_items_by_id(client, owner_headers, trip_id)

    assert response.status_code == 200
    assert items[second_id]["day_number"] == 1
    assert items[second_id]["order_index"] == 0
    assert items[third_id]["day_number"] == 2
    assert items[third_id]["order_index"] == 0
    assert items[first_id]["day_number"] == 2
    assert items[first_id]["order_index"] == 1


def test_user_cannot_reorder_items_from_another_trip(client):
    owner_headers = register_and_login(client, "owner@example.com")
    other_headers = register_and_login(client, "other@example.com")
    trip_id = create_trip(client, owner_headers)
    item_id = create_item(client, owner_headers, trip_id, "私人景點", 1, 0)

    response = client.put(
        "/api/items/reorder",
        headers=other_headers,
        json={
            "reordered_items": [
                {"id": item_id, "order_index": 1, "day_number": 2}
            ]
        },
    )
    items = get_items_by_id(client, owner_headers, trip_id)

    assert response.status_code == 403
    assert items[item_id]["day_number"] == 1
    assert items[item_id]["order_index"] == 0


def test_reorder_rejects_a_payload_that_mixes_unauthorized_items(client):
    owner_headers = register_and_login(client, "owner@example.com")
    other_headers = register_and_login(client, "other@example.com")
    owner_trip_id = create_trip(client, owner_headers, "擁有者行程")
    other_trip_id = create_trip(client, other_headers, "其他人行程")
    owner_item_id = create_item(client, owner_headers, owner_trip_id, "擁有者景點", 1, 0)
    other_item_id = create_item(client, other_headers, other_trip_id, "其他人景點", 1, 0)

    response = client.put(
        "/api/items/reorder",
        headers=owner_headers,
        json={
            "reordered_items": [
                {"id": owner_item_id, "order_index": 1, "day_number": 2},
                {"id": other_item_id, "order_index": 1, "day_number": 2},
            ]
        },
    )
    items = get_items_by_id(client, owner_headers, owner_trip_id)

    assert response.status_code == 403
    assert items[owner_item_id]["day_number"] == 1
    assert items[owner_item_id]["order_index"] == 0
