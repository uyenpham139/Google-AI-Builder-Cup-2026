"""Bounded Gemini failover shared by call replies and fraud analysis."""

import asyncio
from dataclasses import dataclass
from functools import lru_cache
import os
import random
import time
from uuid import uuid4

from google import genai
from google.genai import types
from app.services.gemini_diagnostics import log_diagnostic, provider_diagnostics, safe_text


def timeout_seconds(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if 0 < value <= 60 else default
    except ValueError:
        return default


@dataclass(frozen=True)
class GenerationResult:
    text: str | None = None
    model: str | None = None
    error: str | None = None


@dataclass
class ModelHealth:
    retry_at: float
    probing: bool = False


class GeminiGateway:
    def __init__(self, client=None, models=None, *, cooldown_seconds=30.0, retry_delay=0.25):
        primary = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.8-flash").split(",")
        self.models = tuple(dict.fromkeys(m.strip() for m in (
            models if models is not None else [primary, *fallbacks]
        ) if m.strip()))
        self.client = client
        self.cooldown_seconds = cooldown_seconds
        self.retry_delay = retry_delay
        self._health: dict[str, ModelHealth] = {}

    def _get_client(self):
        if self.client is None and os.getenv("GEMINI_API_KEY"):
            # This gateway owns retries; SDK retries must not multiply the latency.
            self.client = genai.Client(
                api_key=os.environ["GEMINI_API_KEY"],
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            )
        return self.client

    async def generate(self, contents: str, *, timeout: float, config=None, purpose="unspecified") -> GenerationResult:
        request_id = uuid4().hex[:12]
        diagnostic_context = {"request_id": request_id, "purpose": safe_text(purpose)}
        client = self._get_client()
        if client is None:
            log_diagnostic("gemini_unavailable", **diagnostic_context, reason="not_configured", warning=True)
            return GenerationResult(error="not_configured")

        deadline = time.monotonic() + timeout
        candidates = []
        probes = []
        for model in self.models:
            health = self._health.get(model)
            if health is not None:
                if health.probing or health.retry_at > time.monotonic():
                    log_diagnostic(
                        "gemini_skipped", **diagnostic_context, model=safe_text(model), reason="cooldown",
                        retry_after_seconds=round(max(0, health.retry_at - time.monotonic()), 2),
                    )
                    continue
                # Only one request probes a model when its cooldown expires.
                health.probing = True
                probes.append(health)
            candidates.append(model)

        last_error = "cooldown" if not candidates else "timeout"
        try:
            # Try alternate models before retrying failures. At most two rounds.
            for attempt in range(2):
                retry_candidates = []
                if attempt:
                    delay = self.retry_delay + random.uniform(0, 0.1)
                    if deadline - time.monotonic() <= delay:
                        break
                    await asyncio.sleep(delay)
                for model_index, model in enumerate(candidates):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return GenerationResult(error="timeout")
                    retryable = False
                    fatal_error = False
                    retry_after = 0
                    started = time.monotonic()
                    attempt_context = {**diagnostic_context, "model": safe_text(model), "attempt": attempt + 1}
                    try:
                        # Reserve time only when another eligible model can use it.
                        attempt_timeout = remaining
                        if model_index < len(candidates) - 1:
                            attempt_timeout = min(timeout * 0.75, remaining)
                        response = await asyncio.wait_for(
                            client.aio.models.generate_content(model=model, contents=contents, config=config),
                            timeout=attempt_timeout,
                        )
                        if response and response.text and response.text.strip():
                            self._health.pop(model, None)
                            log_diagnostic(
                                "gemini_attempt", **attempt_context, outcome="success",
                                elapsed_ms=round((time.monotonic() - started) * 1000, 2),
                            )
                            return GenerationResult(text=response.text.strip(), model=model)
                        last_error = "empty_response"
                        diagnostic = {"category": "empty_response"}
                    except asyncio.CancelledError:
                        log_diagnostic(
                            "gemini_attempt", **attempt_context, outcome="cancelled",
                            elapsed_ms=round((time.monotonic() - started) * 1000, 2),
                        )
                        raise
                    except (asyncio.TimeoutError, ConnectionError, OSError) as error:
                        last_error = "timeout" if isinstance(error, asyncio.TimeoutError) else "connection_error"
                        diagnostic = {"category": last_error}
                    except Exception as error:
                        code = getattr(error, "code", None)
                        if not isinstance(code, int):
                            code = None
                        last_error = f"http_{code}" if code is not None else "request_failed"
                        retryable = code in (408, 429, 500, 502, 503, 504)
                        diagnostic = provider_diagnostics(error)
                        retry_after = diagnostic.get("retry_after_seconds", 0)
                        fatal_error = code in (400, 401, 403)

                    log_diagnostic(
                        "gemini_attempt", **attempt_context, outcome="failure", warning=True,
                        elapsed_ms=round((time.monotonic() - started) * 1000, 2), **diagnostic,
                    )
                    if fatal_error:
                        # Invalid requests/credentials cannot be fixed by repeating them.
                        return GenerationResult(error=last_error)

                    health = self._health.setdefault(model, ModelHealth(0))
                    health.retry_at = time.monotonic() + max(self.cooldown_seconds, retry_after)
                    if retryable and retry_after == 0:
                        retry_candidates.append(model)
                candidates = retry_candidates
                if not candidates:
                    break
            return GenerationResult(error=last_error)
        finally:
            for health in probes:
                health.probing = False


@lru_cache(maxsize=1)
def get_gemini_gateway():
    mode = os.getenv("GEMINI_API_MODE", "standard").strip().lower()
    if mode == "live":
        from app.services.gemini_live.gateway import GeminiLiveGateway
        return GeminiLiveGateway()
    if mode == "standard":
        return GeminiGateway()
    raise ValueError("GEMINI_API_MODE must be 'standard' or 'live'")
