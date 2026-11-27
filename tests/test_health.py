def test_api_root_returns_service_message(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"message": "API 伺服器運作中！"}
