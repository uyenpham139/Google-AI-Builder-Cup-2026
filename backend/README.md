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
