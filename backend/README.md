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

`ws://localhost:8000/ws/audio` ingests live call audio. Audio lives only in RAM: nothing is written to disk.

1. **Handshake first.** The first text frame must be `INIT_SESSION`:
   `{"type":"INIT_SESSION","sessionId":"<id>","timestamp":<ms>,"audioConfig":{"encoding":"LINEAR16","sampleRate":16000,"channels":1,"chunkDurationMs":100}}`.
   `sessionId` is 1 to 128 characters of `A-Z a-z 0-9 _ -`. A client that reconnects with the same `sessionId` replaces its old session.
2. **Audio as binary frames.** Raw 16-bit little-endian PCM, 16 kHz, mono. One 100 ms chunk is 3200 bytes. No Base64. Empty or odd-length frames are dropped.
3. **Stop.** `{"type":"STOP_STREAM","sessionId":"<id>","reason":"USER_STOPPED"}` ends the session and the server closes with 1000. A plain disconnect also ends it.
4. **No acknowledgements.** The server sends nothing per chunk.

| Close code | Meaning |
|---|---|
| 1000 | Normal end (`STOP_STREAM`) |
| 1008 | Protocol violation: audio before `INIT_SESSION`, invalid or repeated `INIT_SESSION` |
| 1009 | A binary frame larger than 64 KB |
| 1013 | Server busy (100 concurrent sessions) |

A socket that sends no `INIT_SESSION` within 10 s is closed with 1008. A newer connection with the same `sessionId` replaces the old one, and the old socket is closed with 1008.

Each session keeps a 5 s (160,000 byte) ring buffer that overwrites the oldest audio. `AudioSessionContext.get_latest_window(3000)` returns the newest 3 s (96,000 bytes), and `vertex_ai_stream_generator()` yields chunks for the Live API bridge. The code is in `app/services/ingestion/`.

### Tests

```bash
cd backend
python -m pytest tests -q
```
