"""Exercise a real WebSocket connection against the production worker."""

import json
import os
import socket
import subprocess
import sys
import threading
import time

import requests
import socketio
import websocket


def main():
    subprocess.run(
        [sys.executable, "-c", "from app import app, db; ctx=app.app_context(); ctx.push(); db.create_all()"],
        check=True,
    )
    server = subprocess.Popen(
        [
            "gunicorn", "-k", "websocket_worker.OriginCheckedGeventWorker",
            "-w", "1", "--graceful-timeout", "2", "-b", "127.0.0.1:5001", "app:app",
        ],
        env=os.environ.copy(),
    )
    allowed_origin = 'http://localhost:5173'
    denied_origin = 'http://localhost.evil:5173'
    def make_client(origin=allowed_origin):
        return socketio.Client(reconnection=False, websocket_extra_options={'origin': origin})
    client = make_client()
    outsider = make_client()
    outsider_second = make_client()
    short = make_client()
    received = threading.Event()
    leaked = threading.Event()
    client.on("itinerary_updated", lambda _data: received.set())
    outsider.on("itinerary_updated", lambda _data: leaked.set())
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
        empty_polling = requests.get(base + '/socket.io/?EIO=4&transport=polling',
                                     headers={'Origin': ''}, timeout=5)
        assert empty_polling.status_code == 403
        for origin_header in (b'Origin:\r\n', b'Origin: \r\n', b'Origin: null\r\n',
                              b'Origin: http://localhost.evil:5173\r\n'):
            request = (b'GET /socket.io/?EIO=4&transport=websocket HTTP/1.1\r\n'
                       b'Host: 127.0.0.1:5001\r\nUpgrade: websocket\r\n'
                       b'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
                       b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n' + origin_header + b'\r\n')
            with socket.create_connection(('127.0.0.1', 5001), timeout=5) as connection:
                connection.sendall(request)
                status = connection.recv(1024).split(b'\r\n', 1)[0]
                assert status.startswith(b'HTTP/1.1 403 '), status
        no_origin_anonymous = socketio.Client(reconnection=False, websocket_extra_options={'suppress_origin': True})
        try:
            no_origin_anonymous.connect(base, transports=['websocket'], wait_timeout=5)
        except socketio.exceptions.ConnectionError:
            pass
        else:
            no_origin_anonymous.disconnect()
            raise AssertionError('Anonymous client without Origin was accepted')
        anonymous = make_client()
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
        other_credentials = {"email": "other@example.invalid", "password": "test-password"}
        response = requests.post(base + "/api/register", json={**other_credentials, "invite_code": "verification-only-invite"}, timeout=5)
        response.raise_for_status()
        response = requests.post(base + "/api/login", json=other_credentials, timeout=5)
        response.raise_for_status()
        other_token = response.json()["access_token"]
        response = requests.post(base + "/api/trips", headers=headers, json={"title": "test", "start_date": "2026-01-01", "end_date": "2026-01-02"}, timeout=5)
        response.raise_for_status()
        trip_id = response.json()["id"]
        no_origin = socketio.Client(reconnection=False, websocket_extra_options={'suppress_origin': True})
        no_origin.connect(base, auth={'token': token}, transports=['websocket'], wait_timeout=5)
        assert no_origin.call('join_trip', {'trip_id': trip_id}, timeout=5)['ok']
        no_origin.disconnect()
        try:
            unexpected = websocket.create_connection(
                'ws://127.0.0.1:5001/socket.io/?EIO=4&transport=websocket',
                origin=denied_origin, timeout=5)
        except websocket.WebSocketBadStatusException as error:
            assert error.status_code == 403
        else:
            unexpected.close()
            raise AssertionError('Disallowed origin received WebSocket HTTP 101')
        polling_open = requests.get(base + '/socket.io/?EIO=4&transport=polling',
                                    headers={'Origin': allowed_origin}, timeout=5)
        polling_open.raise_for_status()
        polling_sid = json.loads(polling_open.text[1:])['sid']
        try:
            unexpected = websocket.create_connection(
                f'ws://127.0.0.1:5001/socket.io/?EIO=4&transport=websocket&sid={polling_sid}',
                origin=denied_origin, timeout=5)
        except websocket.WebSocketBadStatusException as error:
            assert error.status_code == 403
        else:
            unexpected.close()
            raise AssertionError('Disallowed origin upgraded an existing polling session')
        polling = make_client()
        polling.connect(base, headers={'Origin': allowed_origin}, auth={'token': token}, transports=['polling'], wait_timeout=5)
        assert polling.transport() == 'polling'
        assert polling.call('join_trip', {'trip_id': trip_id}, timeout=5)['ok']
        polling.disconnect()
        upgraded = socketio.Client(reconnection=False, websocket_extra_options={'suppress_origin': True})
        upgraded.connect(base, headers={'Origin': allowed_origin}, auth={'token': token}, transports=['polling', 'websocket'], wait_timeout=5)
        assert upgraded.transport() == 'websocket'
        upgraded.disconnect()
        for transport in ('polling', 'websocket'):
            denied = make_client(denied_origin)
            try:
                request_headers = {'Origin': denied_origin} if transport == 'polling' else {}
                denied.connect(base, headers=request_headers, auth={'token': token}, transports=[transport], wait_timeout=5)
            except socketio.exceptions.ConnectionError:
                pass
            else:
                denied.disconnect()
                raise AssertionError(f'Disallowed origin accepted over {transport}')
        client.connect(base, auth={"token": token}, transports=["websocket"], wait_timeout=5)
        assert client.transport() == "websocket"
        outsider.connect(base, auth={"token": other_token}, transports=["websocket"], wait_timeout=5)
        assert client.call("join_trip", {"trip_id": trip_id}, timeout=5) == {"ok": True, "trip_id": trip_id}
        assert outsider.call("join_trip", {"trip_id": trip_id}, timeout=5) == {"ok": False, "error": "access_denied"}
        response = requests.post(base + "/api/items", headers=headers, json={"trip_id": trip_id, "content": "test"}, timeout=5)
        response.raise_for_status()
        if not received.wait(5):
            raise AssertionError("WebSocket client did not receive itinerary event")
        if leaked.wait(0.5):
            raise AssertionError("Unauthorized client received itinerary event")
        response = requests.post(base + "/api/trips/generate-share", headers=headers,
                                 json={"trip_id": trip_id, "role": "viewer"}, timeout=5)
        response.raise_for_status()
        response = requests.post(base + "/api/trips/accept-share",
                                 headers={"Authorization": "Bearer " + other_token},
                                 json={"share_token": response.json()["share_token"]}, timeout=5)
        response.raise_for_status()
        outsider_second.connect(base, auth={"token": other_token}, transports=["websocket"], wait_timeout=5)
        for connection in (outsider, outsider_second):
            assert connection.call("join_trip", {"trip_id": trip_id}, timeout=5)["ok"]
        removed = threading.Event()
        outsider_second.on("itinerary_updated", lambda _data: removed.set())
        response = requests.delete(base + f"/api/trips/{trip_id}",
                                   headers={"Authorization": "Bearer " + other_token}, timeout=5)
        response.raise_for_status()
        received.clear()
        response = requests.post(base + "/api/items", headers=headers,
                                 json={"trip_id": trip_id, "content": "after exit"}, timeout=5)
        response.raise_for_status()
        assert received.wait(5)
        assert not leaked.wait(0.5) and not removed.wait(0.5)

        script = ("from datetime import timedelta; from app import app, User; "
                  "from flask_jwt_extended import create_access_token; "
                  "ctx=app.app_context(); ctx.push(); "
                  "u=User.query.filter_by(email='verify@example.invalid').first(); "
                  "print(create_access_token(identity=str(u.id), expires_delta=timedelta(seconds=3)))")
        short_token = subprocess.check_output([sys.executable, "-c", script], text=True).strip()
        short.connect(base, auth={"token": short_token}, transports=["websocket"], wait_timeout=5)
        assert short.call("join_trip", {"trip_id": trip_id}, timeout=5)["ok"]
        short_received = threading.Event()
        short.on("itinerary_updated", lambda _data: short_received.set())
        deadline = time.monotonic() + 6
        while short.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not short.connected
        received.clear()
        response = requests.post(base + "/api/items", headers=headers,
                                 json={"trip_id": trip_id, "content": "after expiry"}, timeout=5)
        response.raise_for_status()
        assert received.wait(5) and not short_received.wait(0.5)
        print("PASS: real websocket transport and room event")
    finally:
        for connection in (short, outsider_second):
            if connection.connected:
                connection.disconnect()
        if outsider.connected:
            outsider.disconnect()
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
