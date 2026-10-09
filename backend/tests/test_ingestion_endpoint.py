import json
import os
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.services.ingestion.registry import registry


def init_msg(session_id="sess-1"):
    return json.dumps(
        {
            "type": "INIT_SESSION",
            "sessionId": session_id,
            "timestamp": 1,
            "audioConfig": {"encoding": "LINEAR16", "sampleRate": 16000, "channels": 1, "chunkDurationMs": 100},
        }
    )


def wait_until(predicate, timeout=3.0):
    """The server runs on another thread: poll with real sleeps instead of spinning."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_stream_fills_ring_buffer_in_order():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg())
        for n in range(60):  # 6 s of audio, more than the 5 s window
            ws.send_bytes(bytes([n]) * 3200)
        ws.send_text(json.dumps({"type": "STOP_STREAM", "sessionId": "sess-1"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1000
    assert len(registry) == 0


def test_window_is_96000_bytes_newest_last():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-w"))
        for n in range(60):
            ws.send_bytes(bytes([n]) * 3200)
        assert wait_until(lambda: (c := registry.get("sess-w")) and c.get_latest_window(100)[-1:] == bytes([59]))
        ctx = registry.get("sess-w")
        window = ctx.get_latest_window(3000)
        assert len(window) == 96_000
        assert window[-3200:] == bytes([59]) * 3200


def test_abrupt_disconnect_releases_session():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-abrupt"))
        ws.send_bytes(bytes(3200))
    assert registry.get("sess-abrupt") is None


def test_binary_before_init_closes_1008():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_bytes(bytes(3200))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008
    assert len(registry) == 0


def test_invalid_init_closes_1008():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps({"type": "INIT_SESSION", "sessionId": "ok", "audioConfig": {"encoding": "MULAW"}}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_second_init_closes_1008():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("first"))
        ws.send_text(init_msg("second"))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008
    assert len(registry) == 0


def test_oversized_frame_closes_1009():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-big"))
        ws.send_bytes(bytes(64 * 1024 + 2))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1009


def test_odd_and_empty_frames_are_dropped_not_fatal():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-odd"))
        ws.send_bytes(b"")
        ws.send_bytes(b"\x01\x02\x03")
        ws.send_bytes(b"\x07\x00" * 1600)
        assert wait_until(lambda: (c := registry.get("sess-odd")) and c.ring_buffer.size >= 3200)
        assert registry.get("sess-odd").ring_buffer.size == 3200


def test_malformed_text_is_ignored():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text("not json")
        ws.send_text(init_msg("sess-mal"))
        ws.send_text(json.dumps({"type": "WHAT"}))
        ws.send_bytes(bytes(3200))
    assert registry.get("sess-mal") is None


def test_reconnect_with_same_id_replaces_old_session():
    client = TestClient(app)
    with client.websocket_connect("/ws/audio") as first:
        first.send_text(init_msg("sess-re"))
        first.send_bytes(bytes(3200))
        with client.websocket_connect("/ws/audio") as second:
            second.send_text(init_msg("sess-re"))
            second.send_bytes(b"\x05\x00" * 1600)
            assert wait_until(lambda: (c := registry.get("sess-re")) and c.is_active and c.ring_buffer.size == 3200)
    assert registry.get("sess-re") is None


def test_zero_retention_no_files_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(os.listdir(tmp_path))
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-files"))
        for _ in range(100):
            ws.send_bytes(bytes(3200))
        ws.send_text(json.dumps({"type": "STOP_STREAM"}))
    assert set(os.listdir(tmp_path)) == before


def test_takeover_closes_the_replaced_socket_with_1008():
    client = TestClient(app)
    with client.websocket_connect("/ws/audio") as first:
        first.send_text(init_msg("sess-take"))
        assert wait_until(lambda: registry.get("sess-take") is not None)
        with client.websocket_connect("/ws/audio") as second:
            second.send_text(init_msg("sess-take"))
            with pytest.raises(WebSocketDisconnect) as exc:
                first.receive_text()
            assert exc.value.code == 1008
            assert registry.get("sess-take").is_active


def test_silent_client_is_closed_after_init_timeout(monkeypatch):
    from app.api.websockets import audio

    monkeypatch.setattr(audio, "INIT_TIMEOUT_S", 0.2)
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_session_cap_rejects_with_1013(monkeypatch):
    from app.api.websockets import audio

    monkeypatch.setattr(audio, "MAX_SESSIONS", 1)
    client = TestClient(app)
    with client.websocket_connect("/ws/audio") as first:
        first.send_text(init_msg("cap-1"))
        assert wait_until(lambda: registry.get("cap-1") is not None)
        with client.websocket_connect("/ws/audio") as second:
            second.send_text(init_msg("cap-2"))
            with pytest.raises(WebSocketDisconnect) as exc:
                second.receive_text()
            assert exc.value.code == 1013
