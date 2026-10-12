import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.api.websockets import audio
from app.main import app
from app.services.gemini_live.client import GeminiLiveError


class FakeClient:
    instances = []
    connect_error = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.turns = []
        self.sent = []
        self.disconnected = 0
        self.failed = False
        FakeClient.instances.append(self)

    async def connect(self):
        if FakeClient.connect_error:
            raise FakeClient.connect_error

    async def send_audio(self, chunk):
        self.sent.append(chunk)
        return True

    async def send_text_turn(self, text):
        self.turns.append(text)
        return True

    async def disconnect(self):
        self.disconnected += 1


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.instances = []
    FakeClient.connect_error = None
    monkeypatch.setattr(audio, "GeminiLiveClient", FakeClient)


def test_audio_is_forwarded_and_acked():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_bytes(bytes(3200))
        assert json.loads(ws.receive_text()) == {"status": "received", "bytes": 3200, "forwarded": True}
    assert FakeClient.instances[0].sent == [bytes(3200)]


def test_stop_stream_closes_gracefully_and_cleans_up():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps({"type": "STOP_STREAM"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1000
    assert FakeClient.instances[0].disconnected == 1


def test_client_disconnect_cleans_up():
    with TestClient(app).websocket_connect("/ws/audio"):
        pass
    assert FakeClient.instances[0].disconnected == 1


def test_live_connect_failure_closes_1011():
    FakeClient.connect_error = GeminiLiveError("GEMINI_API_KEY is not set")
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect("/ws/audio") as ws:
            ws.receive_text()
    assert exc.value.code == 1011


def test_malformed_text_frame_is_ignored():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text("not json")
        ws.send_text(json.dumps({"type": "SOMETHING_ELSE"}))
        ws.send_bytes(bytes(3200))
        assert json.loads(ws.receive_text())["status"] == "received"


def test_browser_leaving_during_ack_is_not_an_error(monkeypatch):
    async def gone(self, data):
        raise WebSocketDisconnect(1006)

    monkeypatch.setattr(WebSocket, "send_text", gone)
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_bytes(bytes(3200))
    assert FakeClient.instances[0].disconnected == 1
