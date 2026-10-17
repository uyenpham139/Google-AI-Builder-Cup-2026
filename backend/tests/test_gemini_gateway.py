import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import gemini
from app.services.gemini import GeminiGateway
from app.services.gemini_diagnostics import provider_diagnostics
from google.genai.errors import ClientError


class ApiError(Exception):
    def __init__(self, code):
        self.code = code


def make_gateway(side_effect, **kwargs):
    generate = AsyncMock(side_effect=side_effect)
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    return GeminiGateway(client=client, models=["primary", "secondary"], retry_delay=0, **kwargs), generate


@pytest.fixture(autouse=True)
def no_retry_jitter(monkeypatch):
    monkeypatch.setattr(gemini.random, "uniform", lambda *_: 0)


@pytest.mark.asyncio
async def test_failover_uses_alternate_before_retrying_overloaded_model():
    gateway, generate = make_gateway([ApiError(503), SimpleNamespace(text="OK")])
    result = await gateway.generate("hello", timeout=1)
    assert result.model == "secondary"
    assert result.text == "OK"
    assert [call.kwargs["model"] for call in generate.await_args_list] == ["primary", "secondary"]


@pytest.mark.asyncio
async def test_transient_errors_retry_once_then_cool_down_across_requests():
    gateway, generate = make_gateway(ApiError(503))
    first = await gateway.generate("reply", timeout=1)
    assert first.error == "http_503"
    assert generate.await_count == 4  # Two models, two attempts each.
    second = await gateway.generate("fraud analysis", timeout=1)
    assert second.error == "cooldown"
    assert generate.await_count == 4


@pytest.mark.asyncio
async def test_recovery_clears_cooldown_and_reports_actual_model(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(gemini, "time", SimpleNamespace(monotonic=lambda: now[0]))
    gateway, generate = make_gateway(ApiError(503))
    await gateway.generate("hello", timeout=1)
    now[0] = 31
    generate.side_effect = [SimpleNamespace(text="Recovered"), SimpleNamespace(text="Still healthy")]
    result = await gateway.generate("hello", timeout=1)
    assert result.model == "primary"
    assert result.error is None
    assert (await gateway.generate("next turn", timeout=1)).text == "Still healthy"


@pytest.mark.asyncio
async def test_only_one_request_probes_a_recovering_model():
    gateway, generate = make_gateway(ApiError(503), cooldown_seconds=0)
    await gateway.generate("initial", timeout=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def recovering(**kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(text="Recovered")

    generate.side_effect = recovering
    probe = asyncio.create_task(gateway.generate("probe", timeout=1))
    await started.wait()
    other = await gateway.generate("concurrent request", timeout=1)
    assert other.error == "cooldown"
    release.set()
    assert (await probe).model == "primary"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 403])
async def test_invalid_requests_are_not_retried(code):
    gateway, generate = make_gateway(ApiError(code))
    assert (await gateway.generate("hello", timeout=1)).error == f"http_{code}"
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_missing_model_fails_over_without_retry():
    gateway, generate = make_gateway([ApiError(404), SimpleNamespace(text="OK")])
    assert (await gateway.generate("hello", timeout=1)).model == "secondary"
    assert generate.await_count == 2


@pytest.mark.asyncio
async def test_empty_response_does_not_claim_success():
    gateway, generate = make_gateway([SimpleNamespace(text=" "), SimpleNamespace(text="OK")])
    assert (await gateway.generate("hello", timeout=1)).model == "secondary"


@pytest.mark.asyncio
async def test_deadline_bounds_entire_request_and_cancels_slow_attempts():
    cancelled = []

    async def slow(**kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(kwargs["model"])

    gateway, generate = make_gateway(slow)
    loop = asyncio.get_running_loop()
    start = loop.time()
    result = await gateway.generate("hello", timeout=0.2)
    assert result.error == "timeout"
    assert loop.time() - start < 0.5
    assert cancelled == ["primary", "secondary"]
    assert generate.await_count == 2


@pytest.mark.asyncio
async def test_call_cancellation_is_not_swallowed():
    gateway, _ = make_gateway(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await gateway.generate("hello", timeout=1)


@pytest.mark.asyncio
async def test_single_eligible_model_can_use_full_budget():
    async def slow_response(**kwargs):
        await asyncio.sleep(0.65)
        return SimpleNamespace(text="Valid analysis")

    gateway, _ = make_gateway(slow_response)
    gateway.models = ("primary",)
    result = await gateway.generate("analyze", timeout=0.8)
    assert result.text == "Valid analysis"
    assert result.model == "primary"


@pytest.mark.asyncio
async def test_missing_key_returns_explicit_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = await GeminiGateway().generate("hello", timeout=1)
    assert result.error == "not_configured"


def test_configured_model_order_is_deduplicated(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", " primary, secondary, ,secondary ")
    assert GeminiGateway().models == ("primary", "secondary")


@pytest.mark.asyncio
async def test_diagnostics_capture_quota_details_without_keys_or_prompts(monkeypatch, caplog):
    secret = "test-secret-api-key-should-never-be-logged"
    prompt = "private treasury conversation should never be logged"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    error = ClientError(429, {"error": {
        "status": "RESOURCE_EXHAUSTED", "message": f"Raw error includes {secret} and {prompt}",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                "quotaId": "GenerateRequestsPerDay", "quotaValue": "20",
                "quotaDimensions": {"model": "primary", "location": "global", "credential": secret},
                "description": prompt,
            }]},
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMIT_EXCEEDED",
             "metadata": {"quota_limit": "per-day", "authorization": secret, "request": prompt}},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "60s"},
        ],
    }})
    gateway, generate = make_gateway([error, SimpleNamespace(text="OK")])
    caplog.set_level(logging.INFO, logger="uvicorn.error.gemini")
    result = await gateway.generate(prompt, timeout=1, purpose="analysis")
    assert result.model == "secondary"
    records = [json.loads(record.getMessage()) for record in caplog.records if record.name == "uvicorn.error.gemini"]
    failed = next(record for record in records if record["outcome"] == "failure")
    assert failed["purpose"] == "analysis"
    assert failed["category"] == "quota_exhausted"
    assert failed["quota_violations"][0]["quotaId"] == "GenerateRequestsPerDay"
    assert failed["retry_after_seconds"] == 60
    assert failed["elapsed_ms"] >= 0
    assert secret not in caplog.text
    assert prompt not in caplog.text


@pytest.mark.asyncio
async def test_provider_retry_hint_prevents_immediate_retries_and_extends_cooldown(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(gemini, "time", SimpleNamespace(monotonic=lambda: now[0]))
    error = ClientError(429, {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "60s"},
    ]}})
    gateway, generate = make_gateway(error)
    await gateway.generate("hello", timeout=1)
    assert generate.await_count == 2
    now[0] = 31
    assert (await gateway.generate("hello", timeout=1)).error == "cooldown"
    assert generate.await_count == 2
    now[0] = 61
    generate.side_effect = [SimpleNamespace(text="Recovered")]
    assert (await gateway.generate("hello", timeout=1)).text == "Recovered"


def test_diagnostics_handle_unstructured_errors_without_logging_their_messages():
    diagnostics = provider_diagnostics(RuntimeError("untrusted secret or transcript text"))
    assert diagnostics["category"] == "request_failed"
    assert "untrusted" not in json.dumps(diagnostics)


def test_capacity_error_is_distinguished_from_quota_exhaustion():
    error = ClientError(429, {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "MODEL_CAPACITY_EXHAUSTED"},
    ]}})
    assert provider_diagnostics(error)["category"] == "capacity_exhausted"


def test_credentials_are_redacted_even_inside_allowlisted_quota_fields(monkeypatch):
    secret = "private-api-key-in-provider-data"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    error = ClientError(429, {"error": {"details": [{
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaId": f"quota/{secret}", "quotaDimensions": {"model": secret}}],
    }]}})
    diagnostics = provider_diagnostics(error)
    assert secret not in json.dumps(diagnostics)
    assert diagnostics["quota_violations"][0]["quotaId"] == "quota/[REDACTED]"
