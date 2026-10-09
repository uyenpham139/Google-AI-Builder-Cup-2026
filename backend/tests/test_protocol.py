import json

import pytest

from app.services.ingestion.protocol import InitSession, ProtocolError, StopStream, parse_control


def init_payload(**over):
    payload = {
        "type": "INIT_SESSION",
        "sessionId": "abc-123",
        "timestamp": 1,
        "audioConfig": {"encoding": "LINEAR16", "sampleRate": 16000, "channels": 1, "chunkDurationMs": 100},
    }
    payload.update(over)
    return json.dumps(payload)


def test_valid_init_session():
    assert parse_control(init_payload()) == InitSession(session_id="abc-123")


def test_stop_stream_with_and_without_session_id():
    assert parse_control(json.dumps({"type": "STOP_STREAM", "sessionId": "abc-123"})) == StopStream("abc-123")
    assert parse_control(json.dumps({"type": "STOP_STREAM"})) == StopStream(None)


@pytest.mark.parametrize("text", ["not json", "[]", "42", json.dumps({"type": "SOMETHING_ELSE"}), json.dumps({})])
def test_malformed_or_unknown_is_ignored(text):
    assert parse_control(text) is None


@pytest.mark.parametrize(
    "over",
    [
        {"sessionId": ""},
        {"sessionId": "has space"},
        {"sessionId": "x" * 129},
        {"sessionId": 5},
        {"audioConfig": {"encoding": "MULAW", "sampleRate": 16000, "channels": 1}},
        {"audioConfig": {"encoding": "LINEAR16", "sampleRate": 48000, "channels": 1}},
        {"audioConfig": {"encoding": "LINEAR16", "sampleRate": 16000, "channels": 2}},
        {"audioConfig": None},
    ],
)
def test_invalid_init_session_raises(over):
    with pytest.raises(ProtocolError):
        parse_control(init_payload(**over))
