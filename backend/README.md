# Echo - Backend

This is the backend service for the **Echo** project, built with [FastAPI (Python)](https://fastapi.tiangolo.com/). It handles the secure connection to the Gemini Live API and receives audio streams from the Next.js frontend via WebSockets.

## Directory Structure

This project follows a Domain-Driven Design (DDD) approach integrated with a Multi-Agent architecture:

```text
backend/
├── app/
│   ├── main.py                     # Entrypoint of the FastAPI application
│   ├── core/                       # Core configurations, settings, and logging
│   ├── api/                        # API Routers / Controllers
│   │   ├── rest/                   # Standard REST endpoints
│   │   └── websockets/             # WebSocket endpoints (e.g., Audio Streaming)
│   ├── models/                     # Data models (Pydantic / DB schemas)
│   ├── services/                   # External services integrations
│   │   └── gemini_live/            # Google Gemini Live API WebSocket Client
│   ├── agents/                     # Multi-Agent System Core (Google ADK)
│   │   ├── orchestrator.py         # Main agent for task routing & planning
│   │   ├── tools/                  # Function call tools for agents
│   │   └── specialized/            # Dedicated agents (e.g., Researcher)
│   └── utils/                      # Helper functions and utilities
├── requirements.txt                # Python dependencies
└── Dockerfile                      # Production Docker container definition
```

## Installation & Running

1. **Create a virtual environment:**
   ```bash
   cd backend
   python -m venv .venv
   ```

2. **Activate the virtual environment:**
   - On Windows:
     ```bash
     .venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source .venv/bin/activate
     ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the FastAPI server (Development):**
   ```bash
   fastapi dev app/main.py
   ```
   *Alternatively, using uvicorn directly:*
   ```bash
   uvicorn app.main:app --reload
   ```

5. **Run the FastAPI server (Production):**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   
   The backend API will be available at [http://localhost:8000](http://localhost:8000).

## Audio Streaming Endpoint

The backend exposes a WebSocket endpoint at `ws://localhost:8000/ws/audio`. The frontend connects to this endpoint to stream microphone chunks.

### Protocol

- Binary frames: raw 16 kHz mono 16-bit little-endian PCM. Each is forwarded to the Gemini Live API and acknowledged with `{"status":"received","bytes":N,"forwarded":bool}`. `forwarded: false` means the chunk was dropped (reconnecting, empty or odd-length).
- Send the text frame `{"type":"STOP_STREAM"}` to end the session. The server closes with code `1000`. A plain disconnect is handled the same way.
- Close code `1011` means the Live session could not start or could not be recovered.
- Environment: `GEMINI_API_KEY` (required), `GEMINI_LIVE_MODEL` (default `gemini-3.8-live`), `GEMINI_LIVE_VOICE` (default `Puck`).
- Real-API check: `python scripts/live_smoke_test.py [seconds]` (use `600` for the 10-minute soak).

## Voice Intervenor and Lockdown (Feature 3)

- **Prompt and trigger (ECHO-23).** Each `/ws/audio` session is created with the passive Security Intervenor system prompt (`app/prompts/intervenor_prompt.py`). The model only speaks after a *text* turn that starts with `[SYSTEM ALERT: TRIGGER_BARGE_IN]` and carries the session's random `token=`. The token is never spoken, so someone saying the trigger phrase in the meeting audio is ignored.
- **Session id.** `/ws/audio?sessionId=<id>` (1 to 128 chars of `A-Za-z0-9_-`; otherwise one is generated) lets a risk event find the live session.
- **Downlink (ECHO-24).** Model audio (PCM 24 kHz) is forwarded on the same socket as text frames `{"type":"BARGE_IN_AUDIO","audio":"<base64>","sampleRate":24000}`.
- **Events channel (ECHO-25).** `ws://.../ws/events?sessionId=<id>` is for the Meet extension and the ERP portal. When the risk score is above `0.85` the server sends `{"type":"LOCK_SESSION","sessionId","riskScore","lockReason","acousticFlag","timestamp"}` to every client of that session and writes `incident_logs/<sessionId>` to Cloud Firestore when `GOOGLE_CLOUD_PROJECT` is set. A client that connects after the lock is locked immediately. The lock is final. Close codes: `1008` bad session id, `1013` too many sockets.
- **Risk entry point.** `LockdownService.handle_risk(session_id, score, reason)` is what the Supervisor Agent (Feature 2) calls. For manual rehearsal, set `ECHO_ENABLE_RISK_TRIGGER=1` and `ECHO_INTERNAL_KEY`, then `POST /internal/risk` with header `X-Echo-Internal-Key` and body `{"sessionId","riskScore","reason"}`.
- **Tests:** `python -m pytest tests -q`.
