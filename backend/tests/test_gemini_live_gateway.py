import asyncio
import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from google.genai import types
from google.genai.errors import ClientError

from app.agents.coercion.agent import CoercionEvaluation
from app.services import gemini
from app.services.gemini_live import gateway as live
from app.services.gemini_live.gateway import GeminiLiveGateway


EVALUATION = {
    "entities": {"urgency_level": "HIGH", "requested_amount": "25 million dollars"},
    "coercion_score": 0.95,
    "matched_tactics": ["FORCED_SECRECY", "BYPASS_FOUR_EYES"],
}
ANALYSIS_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json", response_schema=CoercionEvaluation,
)


def tool_message(args=EVALUATION, name="report_risk"):
    return types.LiveServerMessage(tool_call=types.LiveServerToolCall(
        function_calls=[types.FunctionCall(id="risk-1", name=name, args=args)],
    ))


def speech(text=None, *, complete=False):
    return types.LiveServerMessage(server_content=types.LiveServerContent(
        output_transcription=types.Transcription(text=text) if text else None,
        turn_complete=complete,
    ))


def make_gateway(messages=(), *, error=None, gate=None, max_concurrent=2):
    session = SimpleNamespace(send_client_content=AsyncMock(), send_tool_response=AsyncMock())
    entered, closed = [], []

    async def receive():
        if gate is not None:
            await gate.wait()
        if error is not None:
            raise error
        for message in messages:
            yield message

    session.receive = receive

    @asynccontextmanager
    async def connect(**kwargs):
        entered.append(kwargs)
        try:
            yield session
        finally:
            closed.append(True)

    client = SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=Mock(side_effect=connect))))
    return GeminiLiveGateway(client, "gemini-3.8-live", max_concurrent=max_concurrent), session, entered, closed


@pytest.mark.asyncio
async def test_analysis_uses_validated_function_call_instead_of_unsupported_json_mode():
    gateway, session, entered, closed = make_gateway([tool_message()])
    result = await gateway.generate("analyze", config=ANALYSIS_CONFIG, timeout=1, purpose="analysis")
    assert result.model == "gemini-3.8-live"
    assert json.loads(result.text)["coercion_score"] == 0.95
    config = entered[0]["config"]
    declaration = config.tools[0].function_declarations[0]
    assert declaration.parameters_json_schema == CoercionEvaluation.model_json_schema()
    assert declaration.behavior == "BLOCKING"
    assert "response_schema" not in config.model_dump()
    ack = session.send_tool_response.await_args.kwargs["function_responses"][0]
    assert (ack.id, ack.name, ack.response) == ("risk-1", "report_risk", {"accepted": True})
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("messages,reason", [
    ([speech(json.dumps(EVALUATION), complete=True)], "missing_risk_report"),
    ([tool_message({"coercion_score": "invalid"})], "invalid_response"),
    ([tool_message(name="execute_transfer")], "unexpected_tool_call"),
])
async def test_invalid_or_spoken_risk_reports_never_claim_cloud_success(messages, reason):
    gateway, session, _, closed = make_gateway(messages)
    result = await gateway.generate("analyze", config=ANALYSIS_CONFIG, timeout=1)
    assert result.error == reason
    assert result.text is None and result.model is None
    session.send_tool_response.assert_not_awaited()
    assert closed == [True]


@pytest.mark.asyncio
async def test_roleplay_joins_audio_transcription_chunks_and_rejects_empty_audio():
    gateway, session, entered, _ = make_gateway([speech("Hello"), speech(" there.", complete=True)])
    result = await gateway.generate("reply", timeout=1, purpose="roleplay")
    assert result.text == "Hello there."
    assert entered[0]["config"].response_modalities == ["AUDIO"]
    assert entered[0]["config"].output_audio_transcription is not None
    assert session.send_client_content.await_args.kwargs["turn_complete"] is True
    empty, _, _, _ = make_gateway([speech(complete=True)])
    assert (await empty.generate("reply", timeout=1)).error == "empty_response"


@pytest.mark.asyncio
async def test_provider_failure_cools_down_both_features_without_leaking_content(monkeypatch, caplog):
    secret, prompt = "secret-live-api-key", "private treasury conversation"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    now = [0.0]
    monkeypatch.setattr(live, "time", SimpleNamespace(monotonic=lambda: now[0]))
    error = ClientError(429, {"error": {
        "message": f"{secret} {prompt}",
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "60s"}],
    }})
    gateway, _, entered, closed = make_gateway(error=error)
    caplog.set_level(logging.INFO, logger="uvicorn.error.gemini")
    assert (await gateway.generate(prompt, timeout=1, purpose="analysis")).error == "http_429"
    now[0] = 31
    assert (await gateway.generate(prompt, timeout=1, purpose="roleplay")).error == "cooldown"
    assert len(entered) == len(closed) == 1
    now[0] = 61
    assert (await gateway.generate(prompt, timeout=1)).error == "http_429"
    assert len(entered) == 2
    assert prompt not in caplog.text and secret not in caplog.text
    assert '"transport": "live"' in caplog.text


@pytest.mark.asyncio
async def test_deadline_cancels_session_and_call_cancellation_propagates():
    gateway, _, entered, closed = make_gateway(gate=asyncio.Event())
    assert (await gateway.generate("slow", timeout=0.02)).error == "timeout"
    assert len(entered) == len(closed) == 1
    gateway._retry_at = 0
    task = asyncio.create_task(gateway.generate("cancel", timeout=10))
    while len(entered) < 2:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(closed) == 2


@pytest.mark.asyncio
async def test_session_cap_and_queued_deadline_do_not_mark_provider_unavailable():
    gate = asyncio.Event()
    gateway, _, entered, closed = make_gateway([speech("Ready", complete=True)], gate=gate, max_concurrent=1)
    first = asyncio.create_task(gateway.generate("first", timeout=2))
    try:
        while not entered:
            await asyncio.sleep(0)
        assert (await gateway.generate("queued", timeout=0.02)).error == "timeout"
        assert len(entered) == 1
        assert gateway._retry_at == 0
        gate.set()
        assert (await first).text == "Ready"
        assert (await gateway.generate("next", timeout=1)).text == "Ready"
        assert len(closed) == 2
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_credentials_and_unsupported_live_models_are_explicit(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert (await GeminiLiveGateway().generate("hello", timeout=1)).error == "not_configured"
    gateway, _, entered, _ = make_gateway()
    gateway.model = "gemini-3.8-live-extended-thinking"
    assert (await gateway.generate("hello", timeout=1)).error == "unsupported_live_model"
    assert not entered


def test_gateway_factory_selects_transport(monkeypatch):
    try:
        for mode, expected in [("live", GeminiLiveGateway), ("standard", gemini.GeminiGateway)]:
            gemini.get_gemini_gateway.cache_clear()
            monkeypatch.setenv("GEMINI_API_MODE", mode)
            assert isinstance(gemini.get_gemini_gateway(), expected)
        gemini.get_gemini_gateway.cache_clear()
        monkeypatch.setenv("GEMINI_API_MODE", "typo")
        with pytest.raises(ValueError, match="GEMINI_API_MODE"):
            gemini.get_gemini_gateway()
    finally:
        gemini.get_gemini_gateway.cache_clear()
