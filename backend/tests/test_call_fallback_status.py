from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import threading

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.agents.coercion.keyword_guard import CoercionKeywordGuard
from app.api import roleplay
from app.api.websockets import audio
from app.services.gemini import GenerationResult


@pytest.mark.parametrize("role", ["caller", "callee"])
def test_scripted_reply_is_not_reported_as_gemini(monkeypatch, role):
    gateway = SimpleNamespace(generate=AsyncMock(return_value=GenerationResult(error="cooldown")))
    monkeypatch.setattr(roleplay, "get_gemini_gateway", lambda: gateway)
    with TestClient(app) as client:
        response = client.post("/api/call/roleplay/reply", json={"user_message": "Why now?", "role": role})
    assert response.status_code == 200
    result = response.json()
    assert result["reply"]
    assert result["source"] == "scripted"
    assert result["model"] is None
    assert result["fallback_reason"] == "cooldown"


def test_live_reply_reports_actual_failover_model(monkeypatch):
    gateway = SimpleNamespace(generate=AsyncMock(return_value=GenerationResult(text="Live reply", model="secondary")))
    monkeypatch.setattr(roleplay, "get_gemini_gateway", lambda: gateway)
    with TestClient(app) as client:
        response = client.post("/api/call/roleplay/reply", json={"user_message": "Why now?"})
    result = response.json()
    assert result["source"] == "gemini"
    assert result["model"] == "secondary"
    assert result["fallback_reason"] is None


def test_local_analysis_metadata_survives_websocket_and_operator_dismissal(monkeypatch):
    agent = SimpleNamespace(
        keyword_guard=CoercionKeywordGuard(),
        evaluate_intent=AsyncMock(return_value={
            "coercion_score": 0.65, "matched_tactics": [], "tier_executed": "TIER_1_FALLBACK",
            "source": "local_rules", "model": None, "fallback_reason": "http_503",
        }),
    )
    monkeypatch.setattr(audio, "CoercionIntentAgent", lambda: agent)
    with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
        for dismissed in (False, True):
            ws.send_json({"type": "transcript", "text": "Wire money immediately and bypass controls"})
            assert ws.receive_json()["type"] == "TIER1_TRIGGERED"
            result = ws.receive_json()
            assert result["source"] == "local_rules"
            assert result["tier"] == "TIER_1_FALLBACK"
            assert result["model"] is None
            assert result["fallback_reason"] == "http_503"
            if dismissed:
                assert result["action"] == "SUPPRESSED_BY_OPERATOR"
            else:
                ws.send_json({"type": "dismiss_alert", "reason": "Smoke test"})
                assert ws.receive_json()["type"] == "ALERT_DISMISSED"


def test_websocket_remains_responsive_and_coalesces_while_analysis_is_busy(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    async def evaluate(window, **kwargs):
        calls.append(window)
        if len(calls) == 1:
            started.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
        return {"coercion_score": 0.65, "tier_executed": "TIER_1_FALLBACK", "source": "local_rules"}

    agent = SimpleNamespace(keyword_guard=CoercionKeywordGuard(), evaluate_intent=evaluate)
    monkeypatch.setattr(audio, "CoercionIntentAgent", lambda: agent)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/call") as ws:
            ws.send_json({"type": "transcript", "text": "Wire the first payment immediately"})
            assert ws.receive_json()["type"] == "TIER1_TRIGGERED"
            assert started.wait(2)
            for text in ("Wire the second payment immediately", "Wire the third payment immediately"):
                ws.send_json({"type": "transcript", "text": text})
                assert ws.receive_json()["type"] == "TIER1_TRIGGERED"
            ws.send_json({"type": "transcript", "text": "Wire the third payment immediately"})
            assert ws.receive_json()["type"] == "TRANSCRIPT_SKIPPED"
            ws.send_json({"type": "transcript", "text": "Follow normal approval procedures"})
            assert ws.receive_json()["type"] == "STATUS_OK"
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
            release.set()
            for _ in range(2):
                assert ws.receive_json()["source"] == "local_rules"
        assert len(calls) == 2
        assert "third payment" in calls[1]
        assert "Follow normal approval procedures" in calls[1]
        assert calls[1].count("third payment") == 1
    finally:
        release.set()
