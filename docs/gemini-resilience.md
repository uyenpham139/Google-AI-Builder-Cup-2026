# Gemini availability during calls

The call simulator and coercion analysis share a Gemini gateway. It tries the
configured primary model, then the ordered alternatives in
`GEMINI_FALLBACK_MODELS`. Duplicate model names are removed. A failed model is
skipped for 30 seconds across both features. After cooldown, one request probes
the model; success restores normal use.

Transient HTTP failures (408, 429, 500, 502, 503, 504) get at most one retry per
model, after alternatives have been tried and a short randomized backoff. SDK
retries are disabled so they cannot multiply these attempts. Invalid requests
and credential errors are not retried. Empty output, missing models, connection
failures, and timeouts also permit failover.

When Google supplies a retry delay, the gateway skips immediate retries for that
model and extends its cooldown to at least the suggested delay (up to 24 hours).

All attempts and backoff share a total deadline:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Primary model |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.8-flash` | Comma-separated alternatives |
| `GEMINI_ANALYSIS_TIMEOUT_SECONDS` | `20` | Background coercion analysis |
| `GEMINI_ROLEPLAY_TIMEOUT_SECONDS` | `16` | Conversational replies |

When another model is eligible, an attempt uses at most 75% of that feature's
total budget, leaving time for failover. The last or sole eligible model can use
the full remaining budget. This avoids cancelling a valid 11-second analysis at
the previous six-second attempt cutoff. Local transcript screening and its immediate
WebSocket notification do not wait for cloud analysis. Timeouts must be greater
than zero and at most 60 seconds; invalid values use the default. Changing the
configuration requires restarting the backend.

## Transcript request volume

Each call has one background analysis worker. A 150 ms collection window combines
bursts before the first request. While that request is running, newer suspicious
turns replace a single pending context rather than spawning parallel requests.
Benign speech can update that pending context without scheduling analysis on its
own. An identical active, pending, or most recently completed context is skipped.

Consecutive retransmissions of the same speaker/text within two seconds are
acknowledged as `TRANSCRIPT_SKIPPED` and excluded from conversation history.
Whitespace and case differences are ignored for this check. Later repetitions
and another speaker's words remain separate turns. Dismissal clears this duplicate
check so new operator state can be evaluated. Local screening and WebSocket ping
responses remain immediate; disconnecting cancels the worker and its pending work.

## Provider diagnostics

Backend logs contain JSON events named `gemini_attempt`, `gemini_skipped`, and
`gemini_unavailable`. Each generation has a request ID and purpose (`analysis` or
`roleplay`). Attempt events identify the model, attempt number, elapsed time,
outcome, HTTP status, and provider status when available. This retains failures
from every model, rather than reporting only the final failure.

For structured Google errors, an allowlist preserves quota metric/ID/value,
model/location dimensions, provider reason, and retry delay. This can distinguish
a named exhausted quota from a model capacity error. A bare 429 is labeled
`rate_limited` without assuming which quota caused it. Raw error messages, call
transcripts, request bodies, authorization headers, and arbitrary provider metadata
are excluded. Known credential values are redacted from allowed text fields.

## Fallback and recovery

When Gemini cannot respond, fraud analysis continues with the existing local
heuristics and enforcement thresholds. WebSocket analysis messages report
`source: "local_rules"`, `tier: "TIER_1_FALLBACK"`, `model: null`, and a safe
`fallback_reason`, such as `http_503`, `http_429`, `timeout`, or `cooldown`.
Actual cloud analysis reports `source: "gemini"`, `tier: "TIER_2_GEMINI"`, and
the model that answered. Operator dismissal retains this source information.

Roleplay replies report `source: "scripted"` and `model: null` when using a
prepared demo line. Successful cloud replies report `source: "gemini"` and the
actual model. The intentional opening greeting is labeled `scripted_greeting`.

The call page displays separate notices for local protection and scripted
replies. A benign local screening result does not imply Gemini recovered; only
a successful cloud result clears that feature's notice. Risk and lock indicators
remain visible while fallback is active. Raw provider exceptions and API keys
are not returned in fallback metadata.

## Verification

From `backend`, the isolated resilience checks require no live API calls:

```sh
python -m pytest tests/test_gemini_gateway.py tests/test_coercion_agent.py tests/test_call_fallback_status.py tests/test_call_analysis_worker.py -q
```

These cover failover order, bounded retries, shared cooldown, recovery probes,
request deadlines and cancellation, invalid output, and honest HTTP/WebSocket
source metadata. Live model availability still depends on Google and the
project's API quota. See [Google's troubleshooting guidance](https://ai.google.dev/gemini-api/docs/troubleshooting).
