"""Allowlisted provider diagnostics: never serialize raw exceptions or prompts."""

import asyncio
import json
import logging
import os
import re


logger = logging.getLogger("uvicorn.error.gemini")


def safe_text(value) -> str | None:
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value)
    for name, secret in os.environ.items():
        if len(secret) >= 4 and any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"AIza[A-Za-z0-9_-]{20,}", "[REDACTED]", text)
    return text[:200]


def _retry_seconds(value) -> float | None:
    if not isinstance(value, (str, int, float)):
        return None
    try:
        seconds = float(str(value).removesuffix("s"))
        return seconds if 0 <= seconds <= 86400 else None
    except ValueError:
        return None


def provider_diagnostics(error) -> dict:
    code = getattr(error, "code", None)
    result = {"http_status": code if isinstance(code, int) else None, "error_type": safe_text(type(error).__name__)}
    payload = getattr(error, "details", None)
    if not isinstance(payload, dict):
        payload = {}
    payload = payload.get("error", payload)
    if not isinstance(payload, dict):
        payload = {}
    result["provider_status"] = safe_text(payload.get("status", getattr(error, "status", None)))
    details = payload.get("details", [])
    if not isinstance(details, list):
        details = []
    quotas = []
    for detail in details[:10]:
        if not isinstance(detail, dict):
            continue
        kind = detail.get("@type", "")
        if not isinstance(kind, str):
            continue
        if kind.endswith("QuotaFailure"):
            violations = detail.get("violations", [])
            if not isinstance(violations, list):
                continue
            for violation in violations[:8]:
                if not isinstance(violation, dict):
                    continue
                quota = {key: safe_text(violation[key]) for key in ("quotaMetric", "quotaId", "quotaValue") if key in violation}
                dimensions = violation.get("quotaDimensions", {})
                if isinstance(dimensions, dict):
                    quota["dimensions"] = {key: safe_text(dimensions[key]) for key in ("model", "location") if key in dimensions}
                quotas.append(quota)
        elif kind.endswith("ErrorInfo"):
            result["provider_reason"] = safe_text(detail.get("reason"))
            metadata = detail.get("metadata", {})
            if isinstance(metadata, dict):
                result["quota_metadata"] = {
                    key: safe_text(metadata[key]) for key in (
                        "quota_limit", "quota_metric", "quota_limit_value", "quota_location", "model", "service"
                    ) if key in metadata
                }
        elif kind.endswith("RetryInfo"):
            seconds = _retry_seconds(detail.get("retryDelay"))
            if seconds is not None:
                result["retry_after_seconds"] = seconds
    if quotas:
        result["quota_violations"] = quotas
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    if hasattr(headers, "get"):
        seconds = _retry_seconds(headers.get("Retry-After"))
        if seconds is not None:
            result["retry_after_seconds"] = max(seconds, result.get("retry_after_seconds", 0))
    reason = result.get("provider_reason") or ""
    if isinstance(error, asyncio.TimeoutError):
        result["category"] = "timeout"
    elif isinstance(error, (ConnectionError, OSError)):
        result["category"] = "connection_error"
    elif "CAPACITY" in reason:
        result["category"] = "capacity_exhausted"
    elif quotas or "QUOTA" in reason:
        result["category"] = "quota_exhausted"
    else:
        result["category"] = {429: "rate_limited", 503: "service_unavailable"}.get(code, "request_failed")
    return result


def log_diagnostic(event: str, *, warning=False, **fields):
    # Fields supplied here are identifiers/timings or allowlisted diagnostics.
    logger.log(logging.WARNING if warning else logging.INFO, json.dumps({"event": event, **fields}, ensure_ascii=True))
