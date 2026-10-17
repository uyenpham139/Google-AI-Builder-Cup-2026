"""Adapt the call app's analysis/reply interface to Gemini's Live WebSocket API."""

import asyncio
import os
import time
from uuid import uuid4

from google import genai
from google.genai import types

from app.services.gemini import GenerationResult
from app.services.gemini_diagnostics import log_diagnostic, provider_diagnostics, safe_text


class LiveResponseError(ValueError):
    pass


class GeminiLiveGateway:
    def __init__(self, client=None, model=None, *, max_concurrent=2, cooldown_seconds=30):
        self.client = client
        self.model = model or os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
        self._slots = asyncio.Semaphore(max_concurrent)
        self._retry_at = 0.0
        self.cooldown_seconds = cooldown_seconds

    def _get_client(self):
        if self.client is None and os.getenv("GEMINI_API_KEY"):
            self.client = genai.Client(
                api_key=os.environ["GEMINI_API_KEY"],
                http_options=types.HttpOptions(api_version="v1beta"),
            )
        return self.client

    async def generate(self, contents: str, *, timeout: float, config=None, purpose="unspecified") -> GenerationResult:
        context = {
            "request_id": uuid4().hex[:12], "purpose": safe_text(purpose),
            "model": safe_text(self.model), "transport": "live", "attempt": 1,
        }
        # Extended Thinking has a different interaction lifecycle. Translation
        # and transcription models cannot evaluate fraud or roleplay a caller.
        if self.model != "gemini-3.8-live":
            return GenerationResult(error="unsupported_live_model")
        client = self._get_client()
        if client is None:
            return GenerationResult(error="not_configured")
        if self._retry_at > time.monotonic():
            log_diagnostic("gemini_skipped", **context, reason="cooldown")
            return GenerationResult(error="cooldown")
        start = time.monotonic()
        attempted = False
        stage = {"phase": "queue"}

        async def attempt():
            nonlocal attempted
            async with self._slots:
                if self._retry_at > time.monotonic():
                    raise LiveResponseError("cooldown")
                attempted = True
                stage["phase"] = "connect"
                return await self._generate(client, contents, config, stage)

        try:
            text = await asyncio.wait_for(attempt(), timeout=timeout)
            log_diagnostic("gemini_attempt", **context, outcome="success", elapsed_ms=round((time.monotonic() - start) * 1000, 2))
            return GenerationResult(text=text, model=self.model)
        except asyncio.CancelledError:
            log_diagnostic("gemini_attempt", **context, outcome="cancelled", elapsed_ms=round((time.monotonic() - start) * 1000, 2))
            raise
        except LiveResponseError as error:
            reason = str(error)
            diagnostic = {"category": reason}
        except Exception as error:
            diagnostic = provider_diagnostics(error)
            code = diagnostic.get("http_status")
            if not isinstance(code, int) or not 400 <= code <= 599:
                diagnostic["http_status"] = None
                reason = "timeout" if isinstance(error, asyncio.TimeoutError) else "live_unavailable"
                close = getattr(error, "rcvd", None)
                if close is not None and isinstance(getattr(close, "code", None), int):
                    diagnostic["close_code"] = close.code
            else:
                reason = f"http_{code}"
            # Expiring in the local queue says nothing about Google's availability.
            if attempted:
                self._retry_at = time.monotonic() + max(self.cooldown_seconds, diagnostic.get("retry_after_seconds", 0))
        log_diagnostic(
            "gemini_attempt", **context, outcome="failure", warning=True,
            elapsed_ms=round((time.monotonic() - start) * 1000, 2), **stage, **diagnostic,
        )
        return GenerationResult(error=reason)

    async def _generate(self, client, contents, config, stage):
        schema = getattr(config, "response_schema", None)
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction="Follow the user's instructions. Reply in one or two concise spoken sentences.",
        )
        if schema is not None:
            live_config.system_instruction = (
                "You are a fraud risk evaluator. Follow the evaluation rules in the user content. "
                "Always call report_risk exactly once with your evaluation. Do not speak."
            )
            live_config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(
                name="report_risk", description="Report the fraud risk evaluation.",
                parameters_json_schema=schema.model_json_schema(), behavior="BLOCKING",
            )])]
            contents += (
                "\n\nEvaluate the conversation above now. Call report_risk with your evaluation, "
                "including when the risk is low."
            )
        async with client.aio.live.connect(model=self.model, config=live_config) as session:
            stage["phase"] = "send"
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=contents)]), turn_complete=True,
            )
            stage["phase"] = "receive"
            transcript = []
            async for message in session.receive():
                if schema is not None and message.tool_call:
                    for call in message.tool_call.function_calls:
                        if call.name != "report_risk":
                            raise LiveResponseError("unexpected_tool_call")
                        try:
                            result = schema.model_validate(call.args)
                        except ValueError:
                            raise LiveResponseError("invalid_response") from None
                        stage["phase"] = "acknowledge"
                        await session.send_tool_response(function_responses=[types.FunctionResponse(
                            id=call.id, name=call.name, response={"accepted": True},
                        )])
                        return result.model_dump_json()
                content = message.server_content
                if content and content.output_transcription and content.output_transcription.text:
                    transcript.append(content.output_transcription.text)
                if content and content.turn_complete:
                    break
            if schema is not None:
                # Spoken JSON is not a substitute for a validated risk tool call.
                raise LiveResponseError("missing_risk_report")
            text = "".join(transcript).strip()
            if not text:
                raise LiveResponseError("empty_response")
            return text
