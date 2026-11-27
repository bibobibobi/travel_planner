"""Exercise a real WebSocket connection against the production worker."""

import os
import subprocess
import sys
import threading
import time

import requests
import socketio


def main():
    subprocess.run(
        [sys.executable, "-c", "from app import app, db; ctx=app.app_context(); ctx.push(); db.create_all()"],
        check=True,
    )
    server = subprocess.Popen(
        [
            "gunicorn", "-k", "geventwebsocket.gunicorn.workers.GeventWebSocketWorker",
            "-w", "1", "--graceful-timeout", "2", "-b", "127.0.0.1:5001", "app:app",
        ],
        env=os.environ.copy(),
    )
    client = socketio.Client(reconnection=False)
    received = threading.Event()
    client.on("itinerary_updated", lambda _data: received.set())
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Gunicorn exited before becoming ready")
            try:
                requests.get("http://127.0.0.1:5001/", timeout=1).raise_for_status()
                break
            except requests.RequestException:
                time.sleep(0.1)
        else:
            raise RuntimeError("Gunicorn did not become ready")

        base = "http://127.0.0.1:5001"
        anonymous = socketio.Client(reconnection=False)
        try:
            anonymous.connect(base, transports=["websocket"], wait_timeout=5)
        except socketio.exceptions.ConnectionError:
            pass
        else:
            anonymous.disconnect()
            raise AssertionError("Anonymous connection was accepted")
        credentials = {"email": "verify@example.invalid", "password": "test-password"}
        response = requests.post(base + "/api/register", json={**credentials, "invite_code": "verification-only-invite"}, timeout=5)
        response.raise_for_status()
        response = requests.post(base + "/api/login", json=credentials, timeout=5)
        response.raise_for_status()
        token = response.json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        response = requests.post(base + "/api/trips", headers=headers, json={"title": "test", "start_date": "2026-01-01", "end_date": "2026-01-02"}, timeout=5)
        response.raise_for_status()
        trip_id = response.json()["id"]
        client.connect(base, auth={"token": token}, transports=["websocket"], wait_timeout=5)
        assert client.transport() == "websocket"
        client.emit("join_trip", {"trip_id": trip_id})
        time.sleep(0.3)
        response = requests.post(base + "/api/items", headers=headers, json={"trip_id": trip_id, "content": "test"}, timeout=5)
        response.raise_for_status()
        if not received.wait(5):
            raise AssertionError("WebSocket client did not receive itinerary event")
        print("PASS: real websocket transport and room event")
    finally:
        if client.connected:
            client.disconnect()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
