import asyncio
import base64
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.websockets import audio
from app.main import app
from app.services.intervention import runtime
from app.services.intervention.broadcast import SessionBroadcastManager
from app.services.intervention.incidents import InMemoryIncidentLogger
from app.services.intervention.lockdown import LiveSessionRegistry, LockdownService


class FakeLive:
    instances = []
    downlink = None  # PCM the fake "model" speaks as soon as the session opens
    arm_session = None  # session id to arm first (None: speak without a trigger)

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.turns = []
        self.failed = False
        FakeLive.instances.append(self)

    async def connect(self):
        if FakeLive.downlink is not None:
            pcm = FakeLive.downlink
            async def speak():
                runtime.live_sessions.arm(FakeLive.arm_session)  # as the lockdown service does after a trigger
                await self.kwargs["on_audio"](pcm)

            if FakeLive.arm_session is None:
                asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self.kwargs["on_audio"](pcm)))
            else:
                asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(speak()))

    async def send_audio(self, chunk):
        return True

    async def send_text_turn(self, text):
        self.turns.append(text)
        return True

    async def disconnect(self):
        pass


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture(autouse=True)
def fresh_runtime(monkeypatch):
    FakeLive.instances = []
    broadcast, live = SessionBroadcastManager(), LiveSessionRegistry()
    logger = InMemoryIncidentLogger()
    service = LockdownService(broadcast, logger, live)
    monkeypatch.setattr(runtime, "broadcast", broadcast)
    monkeypatch.setattr(runtime, "live_sessions", live)
    monkeypatch.setattr(runtime, "lockdown", service)
    monkeypatch.setattr(audio, "GeminiLiveClient", FakeLive)
    return service, broadcast, live, logger


# ---- /ws/events ----

def test_events_requires_a_valid_session_id():
    for url in ("/ws/events", "/ws/events?sessionId=has space", "/ws/events?sessionId=" + "x" * 129):
        with pytest.raises(WebSocketDisconnect) as exc:
            with TestClient(app).websocket_connect(url) as ws:
                ws.receive_text()
        assert exc.value.code == 1008


def test_two_clients_both_receive_lock_session(fresh_runtime, risk_enabled):
    service, broadcast, _, logger = fresh_runtime
    client = TestClient(app)
    with client.websocket_connect("/ws/events?sessionId=s1") as meet, client.websocket_connect(
        "/ws/events?sessionId=s1"
    ) as erp:
        assert wait_until(lambda: broadcast.count("s1") == 2)
        resp = client.post("/internal/risk", json={"sessionId": "s1", "riskScore": 0.94, "reason": "Fake CFO Voice"},
                           headers={"X-Echo-Internal-Key": "k"})
        assert resp.status_code == 200 and resp.json()["triggered"] is True
        a, b = json.loads(meet.receive_text()), json.loads(erp.receive_text())
        assert a["type"] == b["type"] == "LOCK_SESSION"
        assert a["sessionId"] == "s1" and a["riskScore"] == 0.94
    assert logger.incidents[0]["status"] == "PAYMENT_LOCKED"


def test_client_joining_after_the_lock_is_locked_immediately(fresh_runtime, risk_enabled):
    client = TestClient(app)
    client.post("/internal/risk", json={"sessionId": "s2", "riskScore": 0.99, "reason": "x"},
                headers={"X-Echo-Internal-Key": "k"})
    with client.websocket_connect("/ws/events?sessionId=s2") as late:
        assert json.loads(late.receive_text())["type"] == "LOCK_SESSION"


def test_disconnect_unregisters(fresh_runtime):
    _, broadcast, _, _ = fresh_runtime
    with TestClient(app).websocket_connect("/ws/events?sessionId=s3"):
        assert wait_until(lambda: broadcast.count("s3") == 1)
    assert wait_until(lambda: broadcast.count("s3") == 0)


def test_events_socket_cap(monkeypatch):
    from app.api.websockets import events

    monkeypatch.setattr(events, "MAX_EVENT_SOCKETS", 1)
    client = TestClient(app)
    with client.websocket_connect("/ws/events?sessionId=a"):
        assert wait_until(lambda: runtime.broadcast.total() == 1)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/events?sessionId=b") as second:
                second.receive_text()
        assert exc.value.code == 1013


# ---- /internal/risk ----

@pytest.fixture
def risk_enabled(monkeypatch):
    monkeypatch.setenv("ECHO_ENABLE_RISK_TRIGGER", "1")
    monkeypatch.setenv("ECHO_INTERNAL_KEY", "k")


def test_risk_endpoint_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ECHO_ENABLE_RISK_TRIGGER", raising=False)
    resp = TestClient(app).post("/internal/risk", json={"sessionId": "s", "riskScore": 0.99, "reason": "x"})
    assert resp.status_code == 404


def test_risk_endpoint_needs_the_key(risk_enabled):
    client = TestClient(app)
    body = {"sessionId": "s", "riskScore": 0.99, "reason": "x"}
    assert client.post("/internal/risk", json=body).status_code == 403
    assert client.post("/internal/risk", json=body, headers={"X-Echo-Internal-Key": "wrong"}).status_code == 403


def test_risk_endpoint_rejects_bad_bodies(risk_enabled):
    client = TestClient(app)
    h = {"X-Echo-Internal-Key": "k"}
    assert client.post("/internal/risk", json={"sessionId": "s"}, headers=h).status_code == 422
    assert client.post("/internal/risk", json={"sessionId": "bad id", "riskScore": 0.9, "reason": "x"},
                       headers=h).status_code == 422
    assert client.post("/internal/risk", json={"sessionId": "s", "riskScore": 7, "reason": "x"},
                       headers=h).status_code == 422


def test_below_threshold_does_not_trigger(risk_enabled, fresh_runtime):
    resp = TestClient(app).post("/internal/risk", json={"sessionId": "s", "riskScore": 0.5, "reason": "x"},
                                headers={"X-Echo-Internal-Key": "k"})
    assert resp.json()["triggered"] is False
    assert not fresh_runtime[0].is_locked("s")


# ---- /ws/audio downlink (ECHO-24) and registry (ECHO-23) ----

def test_audio_session_gets_intervenor_prompt_and_is_registered(fresh_runtime):
    _, _, live, _ = fresh_runtime
    with TestClient(app).websocket_connect("/ws/audio?sessionId=call-1") as ws:
        ws.send_bytes(bytes(3200))
        ws.receive_text()
        entry = live.get("call-1")
        assert entry is not None
        client, token = entry
        assert token in client.kwargs["system_instruction"]
    assert live.get("call-1") is None


def test_risk_makes_the_live_model_speak_with_this_sessions_token(risk_enabled, fresh_runtime):
    client = TestClient(app)
    with client.websocket_connect("/ws/audio?sessionId=call-2") as ws:
        ws.send_bytes(bytes(3200))
        ws.receive_text()
        resp = client.post("/internal/risk", json={"sessionId": "call-2", "riskScore": 0.94, "reason": "Fake CFO Voice"},
                           headers={"X-Echo-Internal-Key": "k"})
        assert resp.json()["triggered"] is True
        live_client, token = runtime.live_sessions.get("call-2")
        assert len(live_client.turns) == 1 and f"token={token}" in live_client.turns[0]


def test_downlink_audio_is_forwarded_as_base64_barge_in_frames(monkeypatch):
    pcm = b"\x00\x7f" * 10
    monkeypatch.setattr(FakeLive, "downlink", pcm)
    monkeypatch.setattr(FakeLive, "arm_session", "call-3")
    with TestClient(app).websocket_connect("/ws/audio?sessionId=call-3") as ws:
        frame = json.loads(ws.receive_text())
    assert frame == {"type": "BARGE_IN_AUDIO", "audio": base64.b64encode(pcm).decode(), "sampleRate": 24000}


def test_invalid_session_id_falls_back_to_a_generated_one(fresh_runtime):
    _, _, live, _ = fresh_runtime
    with TestClient(app).websocket_connect("/ws/audio?sessionId=bad id!") as ws:
        ws.send_bytes(bytes(3200))
        ws.receive_text()
        assert live.get("bad id!") is None


def test_unarmed_model_audio_is_not_forwarded_as_barge_in(monkeypatch):
    # The model must not be able to reach the user with audio before the trigger was sent.
    monkeypatch.setattr(FakeLive, "downlink", b"\x01\x00" * 10)
    with TestClient(app).websocket_connect("/ws/audio?sessionId=quiet-1") as ws:
        ws.send_bytes(bytes(3200))
        assert json.loads(ws.receive_text())["status"] == "received"  # first frame is the ack, not audio


def test_second_audio_connection_cannot_hijack_a_live_session(fresh_runtime):
    _, _, live, _ = fresh_runtime
    client = TestClient(app)
    with client.websocket_connect("/ws/audio?sessionId=victim") as first:
        first.send_bytes(bytes(3200))
        first.receive_text()
        original = live.get("victim")
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/audio?sessionId=victim") as attacker:
                attacker.receive_text()
        assert exc.value.code == 1008
        assert live.get("victim") == original


def test_per_session_event_socket_cap(monkeypatch):
    from app.api.websockets import events

    monkeypatch.setattr(events, "MAX_SOCKETS_PER_SESSION", 1)
    client = TestClient(app)
    with client.websocket_connect("/ws/events?sessionId=one"):
        assert wait_until(lambda: runtime.broadcast.count("one") == 1)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/events?sessionId=one") as second:
                second.receive_text()
        assert exc.value.code == 1013
        with client.websocket_connect("/ws/events?sessionId=two"):
            assert wait_until(lambda: runtime.broadcast.count("two") == 1)


def test_non_ascii_key_header_is_403_not_500(risk_enabled):
    resp = TestClient(app).post(
        "/internal/risk",
        json={"sessionId": "s", "riskScore": 0.99, "reason": "x"},
        headers={"X-Echo-Internal-Key": "café".encode("latin-1")},
    )
    assert resp.status_code == 403
