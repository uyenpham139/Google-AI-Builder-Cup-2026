# Feature 3 (ECHO-27): Voice Intervenor, Downlink Playback, Dual-Channel Lockdown

> Executed inline (executing-plans). Commits gated on explicit user authorization.

**Goal:** ECHO-23 (intervenor prompt + context-injected trigger), ECHO-24 (downlink PCM 24 kHz to client + scheduled playback), ECHO-25 (LOCK_SESSION broadcast, Meet overlay, ERP lock, audit log). ECHO-22 already lives in PR #2, which this branch is stacked on.

**Base:** `feat/bidirectional-streaming-gemini-live` (PR #2), by the user's choice. Frontend test runner and extension are from PR #4 and are not on this branch, so this branch adds the same `frontend/vitest.config.mts` (identical content) and only new, non-overlapping extension files.

## Rulings (provisional, user may overrule)
- Gemini API key stack from ECHO-22 stays; tickets say Vertex/ADC. `send_client_content` via google-genai replaces raw `clientContent` JSON.
- **Trigger authenticity:** the intervenor listens to untrusted meeting audio, so a speaker could say the trigger phrase. The system prompt carries a per-session random nonce and only accepts text turns containing `token=<nonce>`; audio can never contain it.
- Ticket unit test says bytes `[0x00,0x7F]` give about +0.9999; little-endian gives 0x7F00 = 32512/32768 = 0.99219. Test asserts the correct value.
- `/ws/audio` takes an optional `?sessionId=` (validated, else random) so a risk event can find the live session. PR #4 uses INIT_SESSION instead; reconcile at the glue step.
- Events channel `/ws/events?sessionId=` (Meet extension and ERP portal both connect). A client joining after the lock receives `LOCK_SESSION` immediately. Lock is one-way and idempotent per session (no unfreeze, per ticket).
- Firestore behind an `IncidentLogger` protocol; real writes only when `GOOGLE_CLOUD_PROJECT` is set; a Firestore failure never blocks the broadcast.
- Risk source is Feature 2 (not built). `handle_risk(session_id, score, reason)` is the seam; `POST /internal/risk` exists only when `ECHO_ENABLE_RISK_TRIGGER=1`.
- Extension: only `extension/src/overlay.js` (+test). Wiring into `content.js` and the manifest waits for PR #4.

## Tasks
1. Prompt + `GeminiLiveClient`: `system_instruction`, `send_text_turn`, `on_audio` downlink callback.
2. `services/intervention/`: triggers, broadcast manager, incident loggers, lockdown service, live-session registry.
3. Endpoints: `/ws/events`, `/ws/audio` downlink + registry, `/internal/risk`.
4. Frontend: vitest, `lib/audio/playback.ts` (BargeInAudioPlayer), `lib/lockdown/channel.ts`, `/erp` page.
5. Extension `overlay.js`.
6. Docs, CI test steps, env example, full verification, one fresh review.

## Review Focus
1. Spoken trigger phrase in meeting audio must not activate the intervenor (nonce).
2. Late-joining ERP/Meet client after lock still gets locked.
3. Dead socket in a broadcast must not block others or raise.
4. Firestore down: lock still broadcasts.
5. Odd-length / empty downlink chunks and a player used after `stopAll`.
