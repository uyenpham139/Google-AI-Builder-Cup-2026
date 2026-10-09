# Feature 1 (ECHO-17): Audio Capture, Streaming and Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the four Feature 1 tickets end to end: browser tab-audio capture to 16 kHz PCM chunks (ECHO-18), a binary WebSocket streamer with session lifecycle (ECHO-19), a backend ingestion gateway with an ephemeral ring buffer (ECHO-20), and a Chrome extension HUD with a live waveform for Google Meet (ECHO-21).

**Architecture:** Browser side is TypeScript in `frontend/lib/audio/` (pure, unit-tested functions plus thin browser adapters) with an AudioWorklet in `frontend/public/` and a `/spike` page to exercise it. Backend side is a new `backend/app/services/ingestion/` package (ring buffer, protocol parser, session context, registry) behind `/ws/audio`. The Chrome extension lives in `extension/` as classic MV3 scripts (no bundler) and is tested from the frontend's vitest run.

**Tech Stack:** Next.js 16 / React 19 / TypeScript, vitest + jsdom (new devDependencies), Web Audio API (AudioWorklet), Python 3.12 + FastAPI, pytest + pytest-asyncio, Chrome Extension Manifest V3.

**Spec:** Jira ECHO-18, ECHO-19, ECHO-20, ECHO-21 under epic ECHO-17 (read-only; written in Vietnamese). Team decisions that **override or narrow** the ticket text:
- Code layout: client audio in `frontend/lib/audio/`; extension in `extension/`.
- JS tests: vitest + jsdom.
- Branch `feat/feature-1-audio-ingestion` is cut from `main`. It does **not** include ECHO-22 (PR #2). Wiring `AudioSessionContext` into `GeminiLiveClient` is a separate follow-up once both land.
- Tickets say "Vertex AI"; only the audio format and protocol matter here, so nothing in this plan depends on the Vertex-vs-Gemini-API choice.

## Global Constraints

- Audio format end to end: raw 16-bit little-endian PCM, 16 kHz, mono, `LINEAR16`. One chunk = 1600 samples = **3200 bytes** = 100 ms.
- Control protocol on `/ws/audio` (text frames): `INIT_SESSION` `{type, sessionId, timestamp, audioConfig:{encoding:"LINEAR16", sampleRate:16000, channels:1, chunkDurationMs:100}}` must be the first message; `STOP_STREAM` `{type, sessionId, reason, timestamp}` ends the session. Audio is binary frames only (no Base64).
- Ring buffer: fixed 160,000 bytes (5 s), overwrite oldest, `get_latest_window(3000)` returns exactly 96,000 bytes once full. No file I/O for audio anywhere (zero retention); per-session RAM under 5 MB.
- Client congestion: if `ws.bufferedAmount` exceeds **64 KB**, drop the chunk. Reconnect at most **3** times with delays 1 s, 2 s, 4 s. Normal close code is **1000**.
- Client performance targets: capture, resample and chunk within 50 ms; no storage of audio in IndexedDB/LocalStorage/globals.
- HUD: Shadow DOM, 60 fps via `requestAnimationFrame`, `AnalyserNode.fftSize = 64`, 10 to 14 bars (this plan uses 12), bar height 2 px floor and 20 px max, accent `#10b981`, bundle under 50 KB.
- Frontend rule from `frontend/AGENTS.md`: this Next.js version has breaking changes; read the relevant guide in `node_modules/next/dist/docs/` before writing any page code.
- Follow `CLAUDE.md`: never commit, push or merge without explicit user authorization (every Commit step below is gated), Jira is read-only.
- Do not run `pnpm install` with lifecycle scripts: the root `prepare` script installs a husky hook that calls `pnpm`, which is not on this machine's PATH and would break commits. Use `--ignore-scripts`, and run pnpm as `npx -y pnpm@10.33.2 ...`.
- Backend commands run from `backend/` with its venv and `python -m pytest`. Frontend commands run from the repo root as `npx -y pnpm@10.33.2 --filter frontend <script>`.

## Review Focus

1. Binary frame arriving before `INIT_SESSION` (protocol violation): server closes 1008 and creates no session (Task 2 test).
2. Same `sessionId` reconnecting while the old socket is still tearing down: new session wins, old one is terminated, the registry never loses the new entry (Task 1 + Task 2 tests).
3. Odd-length, empty or oversized binary frames: dropped (odd/empty) or closed 1009 (oversized); the ring buffer never holds a half sample (Task 2 test).
4. `gracefulDisconnect()` while a reconnect timer is pending: no zombie reconnect afterwards (Task 5 test).
5. User cancels the picker, denies permission, or shares a tab without audio: each gives a distinct, readable error and leaves no live track (Task 4 test).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/ingestion/ring_buffer.py` | Fixed-size circular byte buffer |
| `backend/app/services/ingestion/protocol.py` | Parse and validate control messages |
| `backend/app/services/ingestion/session.py` | `AudioSessionContext`: buffer, queue, lifecycle |
| `backend/app/services/ingestion/registry.py` | Active sessions by id |
| `backend/app/api/websockets/audio.py` | `/ws/audio` endpoint (rewrite of the stub) |
| `backend/tests/test_ring_buffer.py`, `test_session.py`, `test_protocol.py`, `test_ingestion_endpoint.py` | Backend tests |
| `frontend/lib/audio/pcm.ts` | Float32 to Int16, RMS, `Downsampler`, `PcmChunker` |
| `frontend/lib/audio/capture.ts` | `initDisplayMediaStream`, `AudioCapture` |
| `frontend/public/echo-pcm-processor.js` | AudioWorklet: mix to mono, post blocks |
| `frontend/lib/audio/streamer.ts` | `EchoAudioStreamer` |
| `frontend/lib/audio/*.test.ts` | Frontend tests |
| `frontend/app/spike/page.tsx` | Manual test page (replaces the stub) |
| `frontend/vitest.config.ts`, `frontend/package.json` | Test runner |
| `extension/manifest.json`, `background.js`, `content.js` | MV3 shell and glue |
| `extension/src/hud.js`, `extension/src/meet.js` | HUD element and Meet lifecycle |
| `extension/test/*.test.js` | Extension tests |

---

### Task 1: Backend ring buffer, protocol, session, registry (ECHO-20 tasks 1, 2, 4)

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/services/ingestion/{__init__,ring_buffer,protocol,session,registry}.py`
- Test: `backend/tests/{test_ring_buffer,test_protocol,test_session}.py`

**Interfaces:**
- Produces:
  - `EphemeralAudioRingBuffer(capacity_bytes: int = 160_000)` with `.size: int`, `.write(data: bytes) -> None`, `.read_latest(n_bytes: int) -> bytes`, `.get_latest_window(duration_ms: int = 3000) -> bytes`, `.clear() -> None`.
  - `InitSession(session_id: str)`, `StopStream(session_id: str | None)` dataclasses; `ProtocolError(ValueError)`; `parse_control(text: str) -> InitSession | StopStream | None` (`None` for malformed JSON or unknown type; raises `ProtocolError` for an invalid `INIT_SESSION`).
  - `AudioSessionContext(session_id: str, capacity_bytes: int = 160_000, queue_size: int = 100)` with `.session_id`, `.ring_buffer`, `.is_active`, `.dropped_chunks`, `async push_chunk(chunk: bytes)`, `vertex_ai_stream_generator() -> AsyncGenerator[bytes, None]`, `get_latest_window(duration_ms: int = 3000) -> bytes`, `terminate() -> None` (idempotent).
  - `SessionRegistry` with `.register(ctx)` (terminates and replaces an existing session with the same id), `.remove(ctx)` (only removes if `ctx` is the registered object), `.get(session_id)`, `len()`; module-level `registry = SessionRegistry()`.

- [ ] **Step 1: Create the branch state check and add test dependencies**

```bash
git branch --show-current   # expect feat/feature-1-audio-ingestion
```

Append to `backend/requirements.txt` (same lines ECHO-26 uses, so merges stay trivial):

```
pydantic>=2.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

Then, from `backend/`:

```bash
python -m venv .venv
.venv/Scripts/pip install -q -r requirements.txt
```

- [ ] **Step 2: Write the failing ring buffer tests**

`backend/tests/test_ring_buffer.py`:

```python
import pytest

from app.services.ingestion.ring_buffer import EphemeralAudioRingBuffer


def test_rollover_overwrites_oldest():
    buf = EphemeralAudioRingBuffer(capacity_bytes=10)
    buf.write(bytes(range(1, 9)))  # 8 bytes
    assert buf.size == 8
    buf.write(bytes(range(9, 14)))  # 5 more -> 3 oldest dropped
    assert buf.size == 10
    assert buf.read_latest(10) == bytes(range(4, 14))


def test_read_latest_returns_newest_in_order_across_wrap():
    buf = EphemeralAudioRingBuffer(capacity_bytes=10)
    buf.write(bytes(range(0, 7)))
    buf.write(bytes(range(7, 12)))  # wraps
    assert buf.read_latest(4) == bytes([8, 9, 10, 11])


def test_oversized_write_keeps_tail():
    buf = EphemeralAudioRingBuffer(capacity_bytes=4)
    buf.write(bytes(range(10)))
    assert buf.size == 4
    assert buf.read_latest(4) == bytes([6, 7, 8, 9])


def test_empty_write_is_noop():
    buf = EphemeralAudioRingBuffer(capacity_bytes=4)
    buf.write(b"")
    assert buf.size == 0
    assert buf.read_latest(4) == b""


def test_window_is_exactly_96000_bytes_when_full():
    buf = EphemeralAudioRingBuffer()
    for n in range(60):  # 60 * 3200 = 192,000 > 160,000
        buf.write(bytes([n % 256]) * 3200)
    window = buf.get_latest_window(3000)
    assert len(window) == 96_000
    assert window[-3200:] == bytes([59]) * 3200  # newest chunk last


def test_window_never_splits_a_sample():
    buf = EphemeralAudioRingBuffer(capacity_bytes=100)
    buf.write(bytes(range(100)))
    assert len(buf.read_latest(7)) % 2 == 0


def test_clear_zeroes_and_resets():
    buf = EphemeralAudioRingBuffer(capacity_bytes=8)
    buf.write(b"\x01" * 8)
    buf.clear()
    assert buf.size == 0
    assert buf.read_latest(8) == b""
    assert bytes(buf._buf) == bytes(8)


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        EphemeralAudioRingBuffer(capacity_bytes=0)
```

- [ ] **Step 3: Run, expect failure**

Run: `python -m pytest tests/test_ring_buffer.py -q`
Expected: collection error `ModuleNotFoundError: app.services.ingestion`.

- [ ] **Step 4: Implement the ring buffer**

`backend/app/services/ingestion/__init__.py`: empty file.

`backend/app/services/ingestion/ring_buffer.py`:

```python
BYTES_PER_MS = 32  # 16 kHz * 2 bytes


class EphemeralAudioRingBuffer:
    """Fixed-size circular buffer held only in RAM (zero retention)."""

    def __init__(self, capacity_bytes: int = 160_000):
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        self.capacity = capacity_bytes
        self._buf = bytearray(capacity_bytes)
        self._write_pos = 0
        self.size = 0

    def write(self, data: bytes) -> None:
        n = len(data)
        if n == 0:
            return
        if n >= self.capacity:
            self._buf[:] = data[-self.capacity:]
            self._write_pos = 0
            self.size = self.capacity
            return
        end = self._write_pos + n
        if end <= self.capacity:
            self._buf[self._write_pos:end] = data
        else:
            first = self.capacity - self._write_pos
            self._buf[self._write_pos:] = data[:first]
            self._buf[:n - first] = data[first:]
        self._write_pos = end % self.capacity
        self.size = min(self.size + n, self.capacity)

    def read_latest(self, n_bytes: int) -> bytes:
        """Newest `n_bytes` in time order, rounded down to whole 16-bit samples."""
        want = min(max(n_bytes, 0), self.size)
        want -= want % 2
        if want == 0:
            return b""
        start = (self._write_pos - want) % self.capacity
        if start + want <= self.capacity:
            return bytes(self._buf[start:start + want])
        return bytes(self._buf[start:]) + bytes(self._buf[:want - (self.capacity - start)])

    def get_latest_window(self, duration_ms: int = 3000) -> bytes:
        return self.read_latest(duration_ms * BYTES_PER_MS)

    def clear(self) -> None:
        self._buf[:] = bytes(self.capacity)
        self._write_pos = 0
        self.size = 0
```

- [ ] **Step 5: Run, expect pass**

Run: `python -m pytest tests/test_ring_buffer.py -q`
Expected: 8 passed.

- [ ] **Step 6: Write failing protocol tests**

`backend/tests/test_protocol.py`:

```python
import json

import pytest

from app.services.ingestion.protocol import InitSession, ProtocolError, StopStream, parse_control


def init_payload(**over):
    payload = {
        "type": "INIT_SESSION",
        "sessionId": "abc-123",
        "timestamp": 1,
        "audioConfig": {"encoding": "LINEAR16", "sampleRate": 16000, "channels": 1, "chunkDurationMs": 100},
    }
    payload.update(over)
    return json.dumps(payload)


def test_valid_init_session():
    assert parse_control(init_payload()) == InitSession(session_id="abc-123")


def test_stop_stream_with_and_without_session_id():
    assert parse_control(json.dumps({"type": "STOP_STREAM", "sessionId": "abc-123"})) == StopStream("abc-123")
    assert parse_control(json.dumps({"type": "STOP_STREAM"})) == StopStream(None)


@pytest.mark.parametrize("text", ["not json", "[]", "42", json.dumps({"type": "SOMETHING_ELSE"}), json.dumps({})])
def test_malformed_or_unknown_is_ignored(text):
    assert parse_control(text) is None


@pytest.mark.parametrize(
    "over",
    [
        {"sessionId": ""},
        {"sessionId": "has space"},
        {"sessionId": "x" * 129},
        {"sessionId": 5},
        {"audioConfig": {"encoding": "MULAW", "sampleRate": 16000, "channels": 1}},
        {"audioConfig": {"encoding": "LINEAR16", "sampleRate": 48000, "channels": 1}},
        {"audioConfig": {"encoding": "LINEAR16", "sampleRate": 16000, "channels": 2}},
        {"audioConfig": None},
    ],
)
def test_invalid_init_session_raises(over):
    with pytest.raises(ProtocolError):
        parse_control(init_payload(**over))
```

- [ ] **Step 7: Run, expect failure, then implement**

Run: `python -m pytest tests/test_protocol.py -q` (expect `ModuleNotFoundError`).

`backend/app/services/ingestion/protocol.py`:

```python
import json
import re
from dataclasses import dataclass

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ProtocolError(ValueError):
    """The client violated the session protocol."""


@dataclass(frozen=True)
class InitSession:
    session_id: str


@dataclass(frozen=True)
class StopStream:
    session_id: str | None


def parse_control(text: str) -> InitSession | StopStream | None:
    """Parse a text frame. Returns None for malformed or unknown messages."""
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    kind = payload.get("type")
    if kind == "STOP_STREAM":
        session_id = payload.get("sessionId")
        return StopStream(session_id if isinstance(session_id, str) else None)
    if kind != "INIT_SESSION":
        return None

    session_id = payload.get("sessionId")
    if not isinstance(session_id, str) or not SESSION_ID_RE.match(session_id):
        raise ProtocolError("invalid sessionId")
    config = payload.get("audioConfig")
    if (
        not isinstance(config, dict)
        or config.get("encoding") != "LINEAR16"
        or config.get("sampleRate") != 16000
        or config.get("channels") != 1
    ):
        raise ProtocolError("audioConfig must be LINEAR16, 16000 Hz, mono")
    return InitSession(session_id)
```

Run: `python -m pytest tests/test_protocol.py -q`. Expected: all pass.

- [ ] **Step 8: Write failing session and registry tests**

`backend/tests/test_session.py`:

```python
import asyncio

import pytest

from app.services.ingestion.registry import SessionRegistry
from app.services.ingestion.session import AudioSessionContext


@pytest.mark.asyncio
async def test_chunks_reach_buffer_and_stream():
    ctx = AudioSessionContext("s1")
    await ctx.push_chunk(b"\x01\x02" * 1600)
    await ctx.push_chunk(b"\x03\x04" * 1600)
    gen = ctx.vertex_ai_stream_generator()
    assert await anext(gen) == b"\x01\x02" * 1600
    assert await anext(gen) == b"\x03\x04" * 1600
    assert ctx.get_latest_window(100)[-4:] == b"\x03\x04\x03\x04"
    ctx.terminate()


@pytest.mark.asyncio
async def test_full_queue_drops_oldest_not_newest():
    ctx = AudioSessionContext("s1", queue_size=2)
    for n in (1, 2, 3):
        await ctx.push_chunk(bytes([n, 0]))
    gen = ctx.vertex_ai_stream_generator()
    assert await anext(gen) == bytes([2, 0])
    assert await anext(gen) == bytes([3, 0])
    assert ctx.dropped_chunks == 1
    ctx.terminate()


@pytest.mark.asyncio
async def test_terminate_clears_buffer_ends_stream_and_is_idempotent():
    ctx = AudioSessionContext("s1", queue_size=2)
    for n in (1, 2, 3, 4):  # queue is full when terminate runs
        await ctx.push_chunk(bytes([n, 0]))
    ctx.terminate()
    ctx.terminate()
    assert ctx.is_active is False
    assert ctx.ring_buffer.size == 0
    assert ctx.get_latest_window(100) == b""
    assert [c async for c in ctx.vertex_ai_stream_generator()] == []


@pytest.mark.asyncio
async def test_push_after_terminate_is_ignored():
    ctx = AudioSessionContext("s1")
    ctx.terminate()
    await ctx.push_chunk(b"\x01\x00")
    assert ctx.ring_buffer.size == 0


@pytest.mark.asyncio
async def test_consumer_waiting_is_released_by_terminate():
    ctx = AudioSessionContext("s1")
    task = asyncio.create_task(anext(ctx.vertex_ai_stream_generator()))
    await asyncio.sleep(0)
    ctx.terminate()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(task, timeout=1)


def test_registry_register_get_remove():
    reg = SessionRegistry()
    a = AudioSessionContext("same")
    reg.register(a)
    assert reg.get("same") is a and len(reg) == 1
    reg.remove(a)
    assert reg.get("same") is None and len(reg) == 0


def test_registry_replaces_and_terminates_old_session():
    reg = SessionRegistry()
    old, new = AudioSessionContext("same"), AudioSessionContext("same")
    reg.register(old)
    reg.register(new)
    assert old.is_active is False
    assert reg.get("same") is new
    reg.remove(old)  # stale teardown must not evict the new session
    assert reg.get("same") is new
```

- [ ] **Step 9: Run, expect failure, then implement**

Run: `python -m pytest tests/test_session.py -q` (expect `ModuleNotFoundError`).

`backend/app/services/ingestion/session.py`:

```python
import asyncio
from collections.abc import AsyncGenerator

from app.services.ingestion.ring_buffer import EphemeralAudioRingBuffer


class AudioSessionContext:
    """One client's live audio: a 5 s RAM window plus a queue for downstream consumers."""

    def __init__(self, session_id: str, capacity_bytes: int = 160_000, queue_size: int = 100):
        self.session_id = session_id
        self.ring_buffer = EphemeralAudioRingBuffer(capacity_bytes)
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=queue_size)
        self.is_active = True
        self.dropped_chunks = 0

    async def push_chunk(self, chunk: bytes) -> None:
        if not self.is_active:
            return
        self.ring_buffer.write(chunk)
        if self._queue.full():
            self._queue.get_nowait()  # a lagging consumer loses the oldest audio
            self.dropped_chunks += 1
        self._queue.put_nowait(chunk)

    async def vertex_ai_stream_generator(self) -> AsyncGenerator[bytes, None]:
        """Async iterator that feeds the Live API bridge."""
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk

    def get_latest_window(self, duration_ms: int = 3000) -> bytes:
        return self.ring_buffer.get_latest_window(duration_ms)

    def terminate(self) -> None:
        if not self.is_active:
            return
        self.is_active = False
        self.ring_buffer.clear()
        while not self._queue.empty():  # pending audio is discarded, not delivered late
            self._queue.get_nowait()
        self._queue.put_nowait(None)
```

`backend/app/services/ingestion/registry.py`:

```python
from app.services.ingestion.session import AudioSessionContext


class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, AudioSessionContext] = {}

    def register(self, ctx: AudioSessionContext) -> None:
        old = self._sessions.get(ctx.session_id)
        if old is not None and old is not ctx:
            old.terminate()  # a reconnecting client replaces its stale session
        self._sessions[ctx.session_id] = ctx

    def remove(self, ctx: AudioSessionContext) -> None:
        if self._sessions.get(ctx.session_id) is ctx:
            del self._sessions[ctx.session_id]

    def get(self, session_id: str) -> AudioSessionContext | None:
        return self._sessions.get(session_id)

    def __len__(self) -> int:
        return len(self._sessions)


registry = SessionRegistry()
```

- [ ] **Step 10: Run all backend tests**

Run: `python -m pytest tests -q`
Expected: all pass (8 + parametrized protocol cases + 7 session/registry).

- [ ] **Step 11: Commit (only after the user authorizes)**

```bash
git add backend/requirements.txt backend/app/services/ingestion backend/tests
git commit -m "feat(ingestion): add ring buffer, protocol parser and audio session context"
```

---

### Task 2: `/ws/audio` ingestion endpoint (ECHO-20 task 3)

**Files:**
- Modify (rewrite): `backend/app/api/websockets/audio.py`
- Test: `backend/tests/test_ingestion_endpoint.py`

**Interfaces:**
- Consumes: `parse_control`, `InitSession`, `StopStream`, `ProtocolError`, `AudioSessionContext`, `registry`.
- Produces: `/ws/audio` behaviour: first text frame must be a valid `INIT_SESSION`; binary frames before it close 1008; invalid `INIT_SESSION` or a second one closes 1008; binary frame over 64 KB closes 1009; empty or odd-length binary frames are dropped; `STOP_STREAM` or a disconnect ends the session (server close 1000 on `STOP_STREAM`). There are no per-chunk acknowledgements.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_ingestion_endpoint.py`:

```python
import json
import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.services.ingestion.registry import registry


def init_msg(session_id="sess-1"):
    return json.dumps(
        {
            "type": "INIT_SESSION",
            "sessionId": session_id,
            "timestamp": 1,
            "audioConfig": {"encoding": "LINEAR16", "sampleRate": 16000, "channels": 1, "chunkDurationMs": 100},
        }
    )


def test_stream_fills_ring_buffer_in_order():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg())
        for n in range(60):  # 6 s of audio, more than the 5 s window
            ws.send_bytes(bytes([n]) * 3200)
        ws.send_text(json.dumps({"type": "STOP_STREAM", "sessionId": "sess-1"}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1000
    assert len(registry) == 0


def test_window_is_96000_bytes_newest_last():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-w"))
        for n in range(60):
            ws.send_bytes(bytes([n]) * 3200)
        ctx = None
        for _ in range(200):  # the server task may lag the test thread slightly
            ctx = registry.get("sess-w")
            if ctx and ctx.ring_buffer.size == 160_000:
                break
        assert ctx is not None
        window = ctx.get_latest_window(3000)
        assert len(window) == 96_000
        assert window[-3200:] == bytes([59]) * 3200


def test_abrupt_disconnect_releases_session():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-abrupt"))
        ws.send_bytes(bytes(3200))
    assert registry.get("sess-abrupt") is None


def test_binary_before_init_closes_1008():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_bytes(bytes(3200))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008
    assert len(registry) == 0


def test_invalid_init_closes_1008():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(json.dumps({"type": "INIT_SESSION", "sessionId": "ok", "audioConfig": {"encoding": "MULAW"}}))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_second_init_closes_1008():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("first"))
        ws.send_text(init_msg("second"))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008
    assert len(registry) == 0


def test_oversized_frame_closes_1009():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-big"))
        ws.send_bytes(bytes(64 * 1024 + 2))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1009


def test_odd_and_empty_frames_are_dropped_not_fatal():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-odd"))
        ws.send_bytes(b"")
        ws.send_bytes(b"\x01\x02\x03")
        ws.send_bytes(b"\x07\x00" * 1600)
        for _ in range(200):
            ctx = registry.get("sess-odd")
            if ctx and ctx.ring_buffer.size:
                break
        assert registry.get("sess-odd").ring_buffer.size == 3200


def test_malformed_text_is_ignored():
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text("not json")
        ws.send_text(init_msg("sess-mal"))
        ws.send_text(json.dumps({"type": "WHAT"}))
        ws.send_bytes(bytes(3200))
    assert registry.get("sess-mal") is None


def test_reconnect_with_same_id_replaces_old_session():
    client = TestClient(app)
    with client.websocket_connect("/ws/audio") as first:
        first.send_text(init_msg("sess-re"))
        first.send_bytes(bytes(3200))
        with client.websocket_connect("/ws/audio") as second:
            second.send_text(init_msg("sess-re"))
            second.send_bytes(b"\x05\x00" * 1600)
            for _ in range(200):
                ctx = registry.get("sess-re")
                if ctx and ctx.ring_buffer.size == 3200 and ctx.is_active:
                    break
            assert registry.get("sess-re").is_active
    assert registry.get("sess-re") is None


def test_zero_retention_no_files_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(os.listdir(tmp_path))
    with TestClient(app).websocket_connect("/ws/audio") as ws:
        ws.send_text(init_msg("sess-files"))
        for _ in range(100):
            ws.send_bytes(bytes(3200))
        ws.send_text(json.dumps({"type": "STOP_STREAM"}))
    assert set(os.listdir(tmp_path)) == before
```

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_ingestion_endpoint.py -q`
Expected: failures (the current stub acks every frame and has no registry).

- [ ] **Step 3: Rewrite the endpoint**

`backend/app/api/websockets/audio.py`:

```python
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ingestion.protocol import InitSession, ProtocolError, StopStream, parse_control
from app.services.ingestion.registry import registry
from app.services.ingestion.session import AudioSessionContext

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FRAME_BYTES = 64 * 1024


@router.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    session: AudioSessionContext | None = None
    close_code: int | None = 1000

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                close_code = None
                break

            text, data = message.get("text"), message.get("bytes")
            if text is not None:
                try:
                    control = parse_control(text)
                except ProtocolError as exc:
                    logger.warning("Rejected INIT_SESSION: %s", exc)
                    close_code = 1008
                    break
                if isinstance(control, InitSession):
                    if session is not None:
                        close_code = 1008  # INIT_SESSION is allowed exactly once
                        break
                    session = AudioSessionContext(control.session_id)
                    registry.register(session)
                    logger.info("Session %s started", control.session_id)
                elif isinstance(control, StopStream):
                    logger.info("STOP_STREAM received")
                    break
            elif data is not None:
                if session is None:
                    close_code = 1008  # audio before the handshake
                    break
                if len(data) > MAX_FRAME_BYTES:
                    close_code = 1009
                    break
                if data and len(data) % 2 == 0:  # drop empty or half-sample frames
                    await session.push_chunk(data)
    except WebSocketDisconnect:
        close_code = None
    finally:
        if session is not None:
            session.terminate()
            registry.remove(session)
            logger.info("Session %s destroyed", session.session_id)
        if close_code is not None:
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=close_code)
```

- [ ] **Step 4: Run all backend tests and the CI lint gate**

```bash
python -m pytest tests -q
pip install -q flake8
python -m flake8 app tests --count --select=E9,F63,F7,F82 --statistics
```

Expected: all pass; flake8 `0`.

- [ ] **Step 5: Commit (only after the user authorizes)**

```bash
git add backend/app/api/websockets/audio.py backend/tests/test_ingestion_endpoint.py
git commit -m "feat(ingestion): serve /ws/audio with INIT_SESSION handshake and ring buffer"
```

---

### Task 3: Frontend tooling and PCM building blocks (ECHO-18 tasks 2 and 3)

**Files:**
- Modify: `frontend/package.json`, `pnpm-lock.yaml` (via pnpm)
- Create: `frontend/vitest.config.ts`, `frontend/lib/audio/pcm.ts`, `frontend/lib/audio/pcm.test.ts`

**Interfaces:**
- Produces:
  - Constants `TARGET_SAMPLE_RATE = 16000`, `CHUNK_SAMPLES = 1600`.
  - `convertFloat32ToInt16(input: Float32Array): Int16Array` (clamps to [-1, 1]).
  - `computeRms(samples: Float32Array): number`.
  - `class Downsampler { constructor(inputRate: number, outputRate = 16000); process(input: Float32Array): Float32Array }` (stateful, no drift across blocks).
  - `class PcmChunker { constructor(onChunk: (chunk: ArrayBuffer) => void, chunkSamples = 1600); push(samples: Int16Array): void; reset(): void }` (every emitted `ArrayBuffer` is exactly `chunkSamples * 2` bytes).

- [ ] **Step 1: Read the Next.js guide the repo mandates**

```bash
npx -y pnpm@10.33.2 install --frozen-lockfile --ignore-scripts
ls frontend/node_modules/next/dist/docs 2>/dev/null | head
```

Skim the guide on client components and `app/` pages before Task 6 (the code in Tasks 3 to 5 uses no Next APIs). If the docs folder is absent, record that and continue.

- [ ] **Step 2: Add the test runner**

```bash
npx -y pnpm@10.33.2 --filter frontend add -D vitest jsdom --ignore-scripts
```

In `frontend/package.json` add the script `"test": "vitest run"` next to `"lint"`.

`frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["lib/**/*.test.ts", "../extension/test/**/*.test.js"],
  },
});
```

Verify the runner starts: `npx -y pnpm@10.33.2 --filter frontend test` should report "No test files found" or run zero tests without a config error. If the `../extension` glob is rejected, record the error and change `include` to a path the runner accepts before Task 7.

- [ ] **Step 3: Write failing tests**

`frontend/lib/audio/pcm.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import {
  CHUNK_SAMPLES,
  Downsampler,
  PcmChunker,
  computeRms,
  convertFloat32ToInt16,
} from "./pcm";

describe("convertFloat32ToInt16", () => {
  it("maps the ticket's reference values", () => {
    const out = convertFloat32ToInt16(new Float32Array([0, 1, -1, 0.5, -0.5]));
    expect(Array.from(out)).toEqual([0, 32767, -32768, 16383, -16384]);
  });

  it("clamps out-of-range samples instead of wrapping", () => {
    const out = convertFloat32ToInt16(new Float32Array([2, -3]));
    expect(Array.from(out)).toEqual([32767, -32768]);
  });

  it("handles NaN as silence", () => {
    expect(Array.from(convertFloat32ToInt16(new Float32Array([NaN])))).toEqual([0]);
  });
});

describe("computeRms", () => {
  it("is 0 for silence and for empty input", () => {
    expect(computeRms(new Float32Array(10))).toBe(0);
    expect(computeRms(new Float32Array(0))).toBe(0);
  });

  it("is the amplitude for a constant signal", () => {
    expect(computeRms(new Float32Array(8).fill(0.5))).toBeCloseTo(0.5, 6);
  });
});

describe("Downsampler", () => {
  it("turns 480 samples at 48 kHz into 160 at 16 kHz", () => {
    expect(new Downsampler(48000).process(new Float32Array(480)).length).toBe(160);
  });

  it("passes 16 kHz through untouched", () => {
    const input = new Float32Array([0.1, 0.2]);
    expect(new Downsampler(16000).process(input)).toBe(input);
  });

  it("averages each window", () => {
    const out = new Downsampler(48000).process(new Float32Array([0.3, 0.6, 0.9, 1, 1, 1]));
    expect(out[0]).toBeCloseTo(0.6, 5);
    expect(out[1]).toBeCloseTo(1, 5);
  });

  it("produces the same total across 128-frame blocks as in one shot (no drift)", () => {
    const signal = new Float32Array(48000).map((_, i) => Math.sin(i / 10));
    const oneShot = new Downsampler(48000).process(signal);
    const blocked = new Downsampler(48000);
    const parts: number[] = [];
    for (let i = 0; i < signal.length; i += 128) {
      parts.push(...blocked.process(signal.subarray(i, i + 128)));
    }
    expect(parts.length).toBe(oneShot.length);
    for (let i = 0; i < parts.length; i += 997) {
      expect(parts[i]).toBeCloseTo(oneShot[i], 5);
    }
  });

  it("converts 44.1 kHz to about one third of the sample count", () => {
    const out = new Downsampler(44100).process(new Float32Array(44100));
    expect(Math.abs(out.length - 16000)).toBeLessThanOrEqual(2);
  });
});

describe("PcmChunker", () => {
  it("emits 3200-byte buffers however the input is sliced", () => {
    const chunks: ArrayBuffer[] = [];
    const chunker = new PcmChunker((c) => chunks.push(c));
    const samples = new Int16Array(CHUNK_SAMPLES * 3 + 500).map((_, i) => i % 1000);
    for (let i = 0; i < samples.length; i += 333) {
      chunker.push(samples.subarray(i, i + 333));
    }
    expect(chunks).toHaveLength(3);
    expect(chunks.every((c) => c.byteLength === 3200)).toBe(true);
  });

  it("preserves sample order and values across chunk boundaries", () => {
    const chunks: ArrayBuffer[] = [];
    const chunker = new PcmChunker((c) => chunks.push(c), 4);
    chunker.push(new Int16Array([1, 2, 3]));
    chunker.push(new Int16Array([4, 5, 6, 7, 8]));
    expect(Array.from(new Int16Array(chunks[0]))).toEqual([1, 2, 3, 4]);
    expect(Array.from(new Int16Array(chunks[1]))).toEqual([5, 6, 7, 8]);
  });

  it("emits independent buffers (no aliasing of the internal buffer)", () => {
    const chunks: ArrayBuffer[] = [];
    const chunker = new PcmChunker((c) => chunks.push(c), 2);
    chunker.push(new Int16Array([1, 2]));
    chunker.push(new Int16Array([3, 4]));
    expect(Array.from(new Int16Array(chunks[0]))).toEqual([1, 2]);
  });

  it("reset discards a partial chunk", () => {
    const onChunk = vi.fn();
    const chunker = new PcmChunker(onChunk, 4);
    chunker.push(new Int16Array([1, 2, 3]));
    chunker.reset();
    chunker.push(new Int16Array([9]));
    expect(onChunk).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 4: Run, expect failure**

Run: `npx -y pnpm@10.33.2 --filter frontend test`
Expected: FAIL, cannot resolve `./pcm`.

- [ ] **Step 5: Implement**

`frontend/lib/audio/pcm.ts`:

```ts
export const TARGET_SAMPLE_RATE = 16000;
export const CHUNK_SAMPLES = 1600; // 100 ms at 16 kHz

export function convertFloat32ToInt16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const raw = input[i];
    const s = Number.isNaN(raw) ? 0 : Math.max(-1, Math.min(1, raw));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}

export function computeRms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

/**
 * Box-filter downsampler that keeps its position between blocks, so feeding
 * 128-frame audio quanta gives the same result as one big buffer.
 */
export class Downsampler {
  private readonly ratio: number;
  private carry = new Float32Array(0);
  private frac = 0;

  constructor(inputRate: number, outputRate: number = TARGET_SAMPLE_RATE) {
    this.ratio = inputRate / outputRate;
  }

  process(input: Float32Array): Float32Array {
    if (this.ratio === 1) return input;
    const buf = new Float32Array(this.carry.length + input.length);
    buf.set(this.carry);
    buf.set(input, this.carry.length);

    const out: number[] = [];
    let start = this.frac;
    for (;;) {
      const a = Math.round(start);
      const b = Math.round(start + this.ratio);
      if (b > buf.length) break;
      let sum = 0;
      for (let i = a; i < b; i++) sum += buf[i];
      out.push(b > a ? sum / (b - a) : 0);
      start += this.ratio;
    }
    const keep = Math.min(Math.round(start), buf.length);
    this.carry = buf.slice(keep);
    this.frac = start - keep;
    return Float32Array.from(out);
  }
}

/** Accumulates Int16 samples and emits fixed-size ArrayBuffers (default 3200 bytes). */
export class PcmChunker {
  private readonly buf: Int16Array;
  private filled = 0;

  constructor(
    private readonly onChunk: (chunk: ArrayBuffer) => void,
    private readonly chunkSamples: number = CHUNK_SAMPLES,
  ) {
    this.buf = new Int16Array(chunkSamples);
  }

  push(samples: Int16Array): void {
    let i = 0;
    while (i < samples.length) {
      const n = Math.min(this.chunkSamples - this.filled, samples.length - i);
      this.buf.set(samples.subarray(i, i + n), this.filled);
      this.filled += n;
      i += n;
      if (this.filled === this.chunkSamples) {
        this.onChunk(this.buf.slice().buffer);
        this.filled = 0;
      }
    }
  }

  reset(): void {
    this.filled = 0;
  }
}
```

(The bytes are little-endian because every browser platform is little-endian; this is the format the ticket requires.)

- [ ] **Step 6: Run, expect pass; lint and type-check**

```bash
npx -y pnpm@10.33.2 --filter frontend test
npx -y pnpm@10.33.2 --filter frontend lint
npx -y pnpm@10.33.2 --filter frontend exec tsc --noEmit
```

Expected: all tests pass; lint and tsc clean.

- [ ] **Step 7: Commit (only after the user authorizes)**

```bash
git add frontend/package.json frontend/vitest.config.ts frontend/lib/audio/pcm.ts frontend/lib/audio/pcm.test.ts pnpm-lock.yaml
git commit -m "feat(audio): add PCM conversion, downsampler and chunker with vitest"
```

---

### Task 4: Tab audio capture and AudioWorklet (ECHO-18 tasks 1, 2, 4)

**Files:**
- Create: `frontend/lib/audio/capture.ts`, `frontend/lib/audio/capture.test.ts`, `frontend/public/echo-pcm-processor.js`, `frontend/lib/audio/worklet.test.ts`

**Interfaces:**
- Consumes: `Downsampler`, `PcmChunker`, `convertFloat32ToInt16`, `computeRms`, `TARGET_SAMPLE_RATE` from `./pcm`.
- Produces:
  - `type AudioCaptureErrorCode = "UNSUPPORTED" | "PERMISSION_DENIED" | "NO_AUDIO_TRACK"`; `class AudioCaptureError extends Error { code: AudioCaptureErrorCode }`.
  - `initDisplayMediaStream(): Promise<MediaStream>` (video tracks stopped before returning; throws `AudioCaptureError`).
  - `interface AudioCaptureOptions { onAudioChunk(chunk: ArrayBuffer): void; onLevel?(rms: number): void; onEnded?(): void; workletUrl?: string }`.
  - `class AudioCapture { constructor(opts: AudioCaptureOptions); start(): Promise<void>; stop(): Promise<void>; get running(): boolean }`. `onEnded` fires when the user stops sharing (the audio track ends). `stop()` is idempotent.
  - Worklet registered as `"echo-pcm-processor"`; posts one mono `Float32Array` per audio quantum.

- [ ] **Step 1: Write failing capture and worklet tests**

`frontend/lib/audio/capture.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { AudioCapture, AudioCaptureError, initDisplayMediaStream } from "./capture";

function fakeTrack(kind: string) {
  return { kind, stop: vi.fn(), onended: null as null | (() => void), readyState: "live" };
}

function fakeStream(audio: number, video = 1) {
  const audioTracks = Array.from({ length: audio }, () => fakeTrack("audio"));
  const videoTracks = Array.from({ length: video }, () => fakeTrack("video"));
  return {
    audioTracks,
    videoTracks,
    getAudioTracks: () => audioTracks,
    getVideoTracks: () => videoTracks,
    getTracks: () => [...audioTracks, ...videoTracks],
  };
}

function stubDisplayMedia(impl: () => Promise<unknown>) {
  vi.stubGlobal("navigator", { mediaDevices: { getDisplayMedia: vi.fn(impl) } });
}

afterEach(() => vi.unstubAllGlobals());

describe("initDisplayMediaStream", () => {
  it("requests audio with processing disabled and stops video tracks", async () => {
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const result = await initDisplayMediaStream();
    expect(result).toBe(stream);
    expect(stream.videoTracks[0].stop).toHaveBeenCalled();
    expect(stream.audioTracks[0].stop).not.toHaveBeenCalled();
    const call = (navigator.mediaDevices.getDisplayMedia as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.video).toBe(true);
    expect(call.audio).toMatchObject({ echoCancellation: false, noiseSuppression: false, autoGainControl: false });
  });

  it("throws NO_AUDIO_TRACK and stops everything when 'Share audio' was not ticked", async () => {
    const stream = fakeStream(0);
    stubDisplayMedia(async () => stream);
    await expect(initDisplayMediaStream()).rejects.toMatchObject({ code: "NO_AUDIO_TRACK" });
    expect(stream.videoTracks[0].stop).toHaveBeenCalled();
  });

  it("maps a denied or cancelled picker to PERMISSION_DENIED", async () => {
    stubDisplayMedia(async () => {
      throw new DOMException("denied", "NotAllowedError");
    });
    await expect(initDisplayMediaStream()).rejects.toMatchObject({ code: "PERMISSION_DENIED" });
  });

  it("reports UNSUPPORTED when getDisplayMedia is missing", async () => {
    vi.stubGlobal("navigator", {});
    const err = await initDisplayMediaStream().catch((e) => e);
    expect(err).toBeInstanceOf(AudioCaptureError);
    expect(err.code).toBe("UNSUPPORTED");
  });

  it("rethrows unexpected errors untouched", async () => {
    stubDisplayMedia(async () => {
      throw new Error("boom");
    });
    await expect(initDisplayMediaStream()).rejects.toThrow("boom");
  });
});

describe("AudioCapture pipeline", () => {
  function setupAudioGraph(sampleRate: number) {
    const port: { onmessage: null | ((e: { data: Float32Array }) => void) } = { onmessage: null };
    const nodes = { workletConnected: false, closed: false };
    class FakeContext {
      sampleRate = sampleRate;
      destination = {};
      audioWorklet = { addModule: vi.fn(async () => undefined) };
      createMediaStreamSource() {
        return { connect: () => ({ connect: () => undefined }), disconnect: vi.fn() };
      }
      createGain() {
        return { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
      }
      close = vi.fn(async () => {
        nodes.closed = true;
      });
    }
    class FakeWorkletNode {
      port = port;
      connect = vi.fn(() => {
        nodes.workletConnected = true;
        return { connect: vi.fn() };
      });
      disconnect = vi.fn();
    }
    class FakeMediaStream {
      constructor(public tracks: unknown[]) {}
    }
    vi.stubGlobal("AudioContext", FakeContext);
    vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
    vi.stubGlobal("MediaStream", FakeMediaStream);
    return { port, nodes };
  }

  it("emits exact 3200-byte chunks and levels from worklet blocks", async () => {
    const { port } = setupAudioGraph(16000);
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const chunks: ArrayBuffer[] = [];
    const levels: number[] = [];
    const capture = new AudioCapture({ onAudioChunk: (c) => chunks.push(c), onLevel: (l) => levels.push(l) });
    await capture.start();
    expect(capture.running).toBe(true);
    for (let i = 0; i < 25; i++) port.onmessage!({ data: new Float32Array(128).fill(0.25) });
    expect(chunks).toHaveLength(2); // 25 * 128 = 3200 samples = two 1600-sample chunks
    expect(chunks.every((c) => c.byteLength === 3200)).toBe(true);
    expect(levels[0]).toBeCloseTo(0.25, 5);
    await capture.stop();
  });

  it("downsamples when the browser locks the context to 48 kHz", async () => {
    const { port } = setupAudioGraph(48000);
    stubDisplayMedia(async () => fakeStream(1));
    const chunks: ArrayBuffer[] = [];
    const capture = new AudioCapture({ onAudioChunk: (c) => chunks.push(c) });
    await capture.start();
    for (let i = 0; i < 75; i++) port.onmessage!({ data: new Float32Array(128) }); // 9600 samples @ 48k = 3200 @ 16k
    expect(chunks.length).toBeGreaterThanOrEqual(1);
    expect(chunks.every((c) => c.byteLength === 3200)).toBe(true);
    await capture.stop();
  });

  it("fires onEnded and tears down when the user stops sharing", async () => {
    const { nodes } = setupAudioGraph(16000);
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const onEnded = vi.fn();
    const capture = new AudioCapture({ onAudioChunk: () => undefined, onEnded });
    await capture.start();
    stream.audioTracks[0].onended!();
    await vi.waitFor(() => expect(nodes.closed).toBe(true));
    expect(onEnded).toHaveBeenCalledTimes(1);
    expect(capture.running).toBe(false);
  });

  it("stop() is idempotent and stops the audio track", async () => {
    setupAudioGraph(16000);
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const capture = new AudioCapture({ onAudioChunk: () => undefined });
    await capture.start();
    await capture.stop();
    await capture.stop();
    expect(stream.audioTracks[0].stop).toHaveBeenCalled();
  });
});
```

`frontend/lib/audio/worklet.test.ts`:

```ts
import { beforeAll, describe, expect, it, vi } from "vitest";

type Processor = { port: { postMessage: ReturnType<typeof vi.fn> }; process(inputs: Float32Array[][]): boolean };
let ProcessorClass: new () => Processor;
const registerProcessor = vi.fn();

beforeAll(async () => {
  vi.stubGlobal(
    "AudioWorkletProcessor",
    class {
      port = { postMessage: vi.fn() };
    },
  );
  vi.stubGlobal("registerProcessor", registerProcessor);
  await import("../../public/echo-pcm-processor.js");
  ProcessorClass = registerProcessor.mock.calls[0][1];
});

describe("echo-pcm-processor", () => {
  it("registers under the expected name", () => {
    expect(registerProcessor.mock.calls[0][0]).toBe("echo-pcm-processor");
  });

  it("averages stereo channels into mono", () => {
    const p = new ProcessorClass();
    const left = new Float32Array([1, 0.5, 0]);
    const right = new Float32Array([0, 0.5, -1]);
    expect(p.process([[left, right]])).toBe(true);
    const sent = p.port.postMessage.mock.calls[0][0] as Float32Array;
    expect(Array.from(sent)).toEqual([0.5, 0.5, -0.5]);
  });

  it("passes a mono channel through unchanged", () => {
    const p = new ProcessorClass();
    p.process([[new Float32Array([0.1, 0.2])]]);
    const sent = p.port.postMessage.mock.calls[0][0] as Float32Array;
    expect(sent[0]).toBeCloseTo(0.1, 6);
  });

  it("keeps running and posts nothing when there is no input", () => {
    const p = new ProcessorClass();
    expect(p.process([[]])).toBe(true);
    expect(p.process([])).toBe(true);
    expect(p.port.postMessage).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, expect failure**

Run: `npx -y pnpm@10.33.2 --filter frontend test`
Expected: FAIL, cannot resolve `./capture` and the worklet file.

- [ ] **Step 3: Implement the worklet**

`frontend/public/echo-pcm-processor.js`:

```js
// Runs on the audio rendering thread: mixes every input channel down to mono
// and hands each 128-frame block to the main thread. Nothing is stored here.
class EchoPcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || input[0].length === 0) return true;

    const frames = input[0].length;
    const mono = new Float32Array(frames);
    for (let c = 0; c < input.length; c++) {
      const channel = input[c];
      for (let i = 0; i < frames; i++) mono[i] += channel[i];
    }
    if (input.length > 1) {
      for (let i = 0; i < frames; i++) mono[i] /= input.length;
    }
    this.port.postMessage(mono, [mono.buffer]);
    return true;
  }
}

registerProcessor("echo-pcm-processor", EchoPcmProcessor);
```

- [ ] **Step 4: Implement capture**

`frontend/lib/audio/capture.ts`:

```ts
import {
  Downsampler,
  PcmChunker,
  TARGET_SAMPLE_RATE,
  computeRms,
  convertFloat32ToInt16,
} from "./pcm";

export type AudioCaptureErrorCode = "UNSUPPORTED" | "PERMISSION_DENIED" | "NO_AUDIO_TRACK";

export class AudioCaptureError extends Error {
  constructor(
    public readonly code: AudioCaptureErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "AudioCaptureError";
  }
}

/** Opens the tab picker and returns a stream that holds audio tracks only. */
export async function initDisplayMediaStream(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new AudioCaptureError("UNSUPPORTED", "This browser cannot capture tab audio.");
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: true, // browsers refuse audio capture without a video request
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "NotAllowedError") {
      throw new AudioCaptureError("PERMISSION_DENIED", "Screen sharing was cancelled or denied.");
    }
    throw err;
  }

  if (stream.getAudioTracks().length === 0) {
    stream.getTracks().forEach((t) => t.stop());
    throw new AudioCaptureError(
      "NO_AUDIO_TRACK",
      "No audio was shared. Choose the meeting tab and tick 'Share tab audio'.",
    );
  }
  stream.getVideoTracks().forEach((t) => t.stop());
  return stream;
}

export interface AudioCaptureOptions {
  onAudioChunk: (chunk: ArrayBuffer) => void;
  onLevel?: (rms: number) => void;
  onEnded?: () => void;
  workletUrl?: string;
}

export class AudioCapture {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private mute: GainNode | null = null;
  private stopping = false;

  constructor(private readonly opts: AudioCaptureOptions) {}

  get running(): boolean {
    return this.ctx !== null;
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.stopping = false;
    const stream = await initDisplayMediaStream();
    const track = stream.getAudioTracks()[0];

    try {
      // Ask for 16 kHz; if the browser keeps a hardware rate, Downsampler covers it.
      const ctx = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      await ctx.audioWorklet.addModule(this.opts.workletUrl ?? "/echo-pcm-processor.js");

      const downsampler = new Downsampler(ctx.sampleRate);
      const chunker = new PcmChunker((chunk) => this.opts.onAudioChunk(chunk));
      const node = new AudioWorkletNode(ctx, "echo-pcm-processor");
      node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        const mono = event.data;
        this.opts.onLevel?.(computeRms(mono));
        chunker.push(convertFloat32ToInt16(downsampler.process(mono)));
      };

      // The worklet only runs while connected to the destination; a zero-gain
      // node keeps it alive without playing the meeting a second time.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      const source = ctx.createMediaStreamSource(new MediaStream([track]));
      source.connect(node);
      node.connect(mute);
      mute.connect(ctx.destination);

      this.stream = stream;
      this.ctx = ctx;
      this.source = source;
      this.node = node;
      this.mute = mute;
      track.onended = () => {
        void this.stop().then(() => this.opts.onEnded?.());
      };
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      throw err;
    }
  }

  async stop(): Promise<void> {
    if (this.stopping || !this.ctx) return;
    this.stopping = true;
    const { stream, ctx, source, node, mute } = this;
    this.stream = this.ctx = this.source = this.node = this.mute = null;

    if (node) node.port.onmessage = null;
    source?.disconnect();
    node?.disconnect();
    mute?.disconnect();
    stream?.getTracks().forEach((t) => {
      t.onended = null;
      t.stop();
    });
    await ctx.close();
  }
}
```

- [ ] **Step 5: Run, expect pass; lint and type-check**

```bash
npx -y pnpm@10.33.2 --filter frontend test
npx -y pnpm@10.33.2 --filter frontend lint
npx -y pnpm@10.33.2 --filter frontend exec tsc --noEmit
```

Expected: all pass. If `fakeStream` casts fail strict typing in tests, cast at the stub boundary (`as unknown as MediaStream`) rather than loosening the production types.

- [ ] **Step 6: Commit (only after the user authorizes)**

```bash
git add frontend/lib/audio/capture.ts frontend/lib/audio/capture.test.ts frontend/lib/audio/worklet.test.ts frontend/public/echo-pcm-processor.js
git commit -m "feat(audio): capture tab audio and emit 16 kHz PCM chunks via AudioWorklet"
```

---

### Task 5: WebSocket streamer with session lifecycle (ECHO-19)

**Files:**
- Create: `frontend/lib/audio/streamer.ts`, `frontend/lib/audio/streamer.test.ts`

**Interfaces:**
- Produces:
  - `type ConnectionState = "DISCONNECTED" | "CONNECTING" | "CONNECTED" | "RECONNECTING" | "ERROR"`.
  - `interface SessionHandshakeMessage` and `interface StopStreamMessage` exactly as in ECHO-19 (fields `type, sessionId, timestamp, audioConfig` / `type, sessionId, reason, timestamp`; `reason` is `"USER_STOPPED" | "MEETING_ENDED" | "ERROR"`).
  - `interface StreamerOptions { onStateChange?(s: ConnectionState): void; onBufferWarning?(bufferedAmount: number): void; webSocketImpl?: typeof WebSocket; reconnectDelaysMs?: number[] }` (default delays `[1000, 2000, 4000]`).
  - `class EchoAudioStreamer { constructor(wsUrl: string, sessionId: string, opts?: StreamerOptions); get state(): ConnectionState; connect(): Promise<void>; sendAudioChunk(chunk: ArrayBuffer): boolean; gracefulDisconnect(reason?): void }`.
  - `attachMeetingLifecycle(audioTrack: MediaStreamTrack, streamer: EchoAudioStreamer, onSessionTerminated: () => void): void`.

- [ ] **Step 1: Write failing tests**

`frontend/lib/audio/streamer.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EchoAudioStreamer, attachMeetingLifecycle } from "./streamer";

class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  static CLOSED = 3;
  readyState = 0;
  binaryType = "blob";
  bufferedAmount = 0;
  sent: (string | ArrayBuffer)[] = [];
  closedWith: [number?, string?] | null = null;
  onopen: null | (() => void) = null;
  onerror: null | ((e: unknown) => void) = null;
  onclose: null | ((e: { code: number }) => void) = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }
  close(code?: number, reason?: string) {
    this.closedWith = [code, reason];
    this.readyState = FakeSocket.CLOSED;
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
  drop(code = 1006) {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.({ code });
  }
  fail() {
    this.onerror?.(new Event("error"));
    this.drop(1006);
  }
}

const last = () => FakeSocket.instances[FakeSocket.instances.length - 1];
const chunk = () => new ArrayBuffer(3200);

function make(opts = {}) {
  return new EchoAudioStreamer("ws://test/ws/audio", "sess-1", {
    webSocketImpl: FakeSocket as unknown as typeof WebSocket,
    ...opts,
  });
}

async function connected(opts = {}) {
  const s = make(opts);
  const p = s.connect();
  last().open();
  await p;
  return s;
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeSocket);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("handshake", () => {
  it("sends INIT_SESSION first, as text, before any audio", async () => {
    const s = await connected();
    const first = JSON.parse(last().sent[0] as string);
    expect(first).toMatchObject({
      type: "INIT_SESSION",
      sessionId: "sess-1",
      audioConfig: { encoding: "LINEAR16", sampleRate: 16000, channels: 1, chunkDurationMs: 100 },
    });
    expect(typeof first.timestamp).toBe("number");
    expect(last().binaryType).toBe("arraybuffer");
    expect(s.state).toBe("CONNECTED");
  });

  it("refuses audio before the socket is open", () => {
    const s = make();
    void s.connect();
    expect(s.sendAudioChunk(chunk())).toBe(false);
    expect(last().sent).toHaveLength(0);
  });

  it("rejects connect() when the socket errors before opening, without auto-retrying", async () => {
    const s = make();
    const p = s.connect();
    const rejected = expect(p).rejects.toBeDefined();
    last().fail();
    await rejected;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});

describe("congestion control", () => {
  it("sends binary frames when the buffer is healthy", async () => {
    const s = await connected();
    const buf = chunk();
    expect(s.sendAudioChunk(buf)).toBe(true);
    expect(last().sent[1]).toBe(buf);
  });

  it("drops the chunk and warns above 64 KB buffered", async () => {
    const onBufferWarning = vi.fn();
    const s = await connected({ onBufferWarning });
    last().bufferedAmount = 70_000;
    expect(s.sendAudioChunk(chunk())).toBe(false);
    expect(last().sent).toHaveLength(1); // only the handshake
    expect(onBufferWarning).toHaveBeenCalledWith(70_000);
  });

  it("still sends at exactly 64 KB", async () => {
    const s = await connected();
    last().bufferedAmount = 64 * 1024;
    expect(s.sendAudioChunk(chunk())).toBe(true);
  });
});

describe("graceful shutdown", () => {
  it("sends STOP_STREAM last and closes with 1000", async () => {
    const s = await connected();
    s.gracefulDisconnect("USER_STOPPED");
    const sock = FakeSocket.instances[0];
    const stop = JSON.parse(sock.sent[sock.sent.length - 1] as string);
    expect(stop).toMatchObject({ type: "STOP_STREAM", sessionId: "sess-1", reason: "USER_STOPPED" });
    expect(sock.closedWith?.[0]).toBe(1000);
    expect(s.state).toBe("DISCONNECTED");
  });

  it("is safe to call twice and before connecting", async () => {
    make().gracefulDisconnect();
    const s = await connected();
    s.gracefulDisconnect();
    expect(() => s.gracefulDisconnect()).not.toThrow();
  });

  it("does not reconnect after a deliberate close", async () => {
    const s = await connected();
    s.gracefulDisconnect();
    FakeSocket.instances[0].drop(1000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("cancels a pending reconnect timer (no zombie socket afterwards)", async () => {
    const s = await connected();
    last().drop(1006);
    expect(s.state).toBe("RECONNECTING");
    s.gracefulDisconnect();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(s.state).toBe("DISCONNECTED");
  });
});

describe("reconnect", () => {
  it("retries after 1s, 2s, 4s, re-sends INIT_SESSION, then gives up", async () => {
    const onStateChange = vi.fn();
    const s = await connected({ onStateChange });
    last().drop(1006);
    expect(s.state).toBe("RECONNECTING");

    await vi.advanceTimersByTimeAsync(999);
    expect(FakeSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(2);
    last().open();
    expect(JSON.parse(last().sent[0] as string).type).toBe("INIT_SESSION");
    expect(s.state).toBe("CONNECTED");

    // Attempt counter resets after a successful reopen.
    last().drop(1006);
    await vi.advanceTimersByTimeAsync(1000);
    expect(FakeSocket.instances).toHaveLength(3);
    last().fail();
    await vi.advanceTimersByTimeAsync(2000);
    expect(FakeSocket.instances).toHaveLength(4);
    last().fail();
    await vi.advanceTimersByTimeAsync(4000);
    expect(FakeSocket.instances).toHaveLength(5);
    last().fail();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.instances).toHaveLength(5);
    expect(s.state).toBe("DISCONNECTED");
    expect(onStateChange).toHaveBeenCalledWith("RECONNECTING");
  });

  it("does not reconnect after a server-side normal close", async () => {
    const s = await connected();
    last().drop(1000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(s.state).toBe("DISCONNECTED");
  });
});

describe("attachMeetingLifecycle", () => {
  it("sends STOP_STREAM and notifies when the track ends", async () => {
    const s = await connected();
    const track = { onended: null as null | (() => void) } as unknown as MediaStreamTrack;
    const done = vi.fn();
    attachMeetingLifecycle(track, s, done);
    track.onended!(new Event("ended"));
    const sock = FakeSocket.instances[0];
    expect(JSON.parse(sock.sent[sock.sent.length - 1] as string).type).toBe("STOP_STREAM");
    expect(done).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run, expect failure**

Run: `npx -y pnpm@10.33.2 --filter frontend test`
Expected: FAIL, cannot resolve `./streamer`.

- [ ] **Step 3: Implement**

`frontend/lib/audio/streamer.ts`:

```ts
export type ConnectionState = "DISCONNECTED" | "CONNECTING" | "CONNECTED" | "RECONNECTING" | "ERROR";

export interface SessionHandshakeMessage {
  type: "INIT_SESSION";
  sessionId: string;
  timestamp: number;
  audioConfig: {
    encoding: "LINEAR16";
    sampleRate: 16000;
    channels: 1;
    chunkDurationMs: 100;
  };
}

export interface StopStreamMessage {
  type: "STOP_STREAM";
  sessionId: string;
  reason: "USER_STOPPED" | "MEETING_ENDED" | "ERROR";
  timestamp: number;
}

export interface StreamerOptions {
  onStateChange?: (state: ConnectionState) => void;
  onBufferWarning?: (bufferedAmount: number) => void;
  webSocketImpl?: typeof WebSocket;
  reconnectDelaysMs?: number[];
}

const MAX_BUFFERED_BYTES = 64 * 1024;
const WS_OPEN = 1;

export class EchoAudioStreamer {
  private ws: WebSocket | null = null;
  private _state: ConnectionState = "DISCONNECTED";
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  private readonly delays: number[];

  constructor(
    private readonly wsUrl: string,
    private readonly sessionId: string,
    private readonly opts: StreamerOptions = {},
  ) {
    this.delays = opts.reconnectDelaysMs ?? [1000, 2000, 4000];
  }

  get state(): ConnectionState {
    return this._state;
  }

  private setState(next: ConnectionState) {
    if (this._state === next) return;
    this._state = next;
    this.opts.onStateChange?.(next);
  }

  /** Opens the socket. A failure of this first attempt rejects and is not retried. */
  connect(): Promise<void> {
    this.intentionalClose = false;
    this.setState("CONNECTING");
    return this.openSocket();
  }

  private openSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const Impl = this.opts.webSocketImpl ?? WebSocket;
      const ws = new Impl(this.wsUrl);
      ws.binaryType = "arraybuffer"; // audio goes out as raw binary frames, never Base64
      this.ws = ws;
      let opened = false;

      ws.onopen = () => {
        opened = true;
        this.reconnectAttempts = 0;
        this.sendHandshake(ws);
        this.setState("CONNECTED");
        resolve();
      };
      ws.onerror = (err) => {
        if (!opened) reject(err);
      };
      ws.onclose = (event) => {
        if (this.ws !== ws) return;
        this.ws = null;
        if (opened && event.code !== 1000 && !this.intentionalClose) {
          this.scheduleReconnect();
        } else if (opened) {
          this.setState("DISCONNECTED");
        }
      };
    });
  }

  private sendHandshake(ws: WebSocket) {
    const handshake: SessionHandshakeMessage = {
      type: "INIT_SESSION",
      sessionId: this.sessionId,
      timestamp: Date.now(),
      audioConfig: { encoding: "LINEAR16", sampleRate: 16000, channels: 1, chunkDurationMs: 100 },
    };
    ws.send(JSON.stringify(handshake));
  }

  private scheduleReconnect() {
    if (this.intentionalClose) return;
    if (this.reconnectAttempts >= this.delays.length) {
      this.setState("DISCONNECTED");
      return;
    }
    const delay = this.delays[this.reconnectAttempts++];
    this.setState("RECONNECTING");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket().catch(() => this.scheduleReconnect());
    }, delay);
  }

  /** Returns false when the chunk was not sent (not connected, or the network is backed up). */
  sendAudioChunk(chunk: ArrayBuffer): boolean {
    const ws = this.ws;
    if (!ws || ws.readyState !== WS_OPEN) return false;
    if (ws.bufferedAmount > MAX_BUFFERED_BYTES) {
      this.opts.onBufferWarning?.(ws.bufferedAmount);
      return false; // keep the stream real-time: drop instead of queueing latency
    }
    ws.send(chunk);
    return true;
  }

  gracefulDisconnect(reason: StopStreamMessage["reason"] = "USER_STOPPED"): void {
    this.intentionalClose = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      if (ws.readyState === WS_OPEN) {
        const stop: StopStreamMessage = {
          type: "STOP_STREAM",
          sessionId: this.sessionId,
          reason,
          timestamp: Date.now(),
        };
        ws.send(JSON.stringify(stop));
      }
      ws.close(1000, "Normal Closure");
    }
    this.setState("DISCONNECTED");
  }
}

/** Ends the stream cleanly when the user presses Chrome's "Stop sharing". */
export function attachMeetingLifecycle(
  audioTrack: MediaStreamTrack,
  streamer: EchoAudioStreamer,
  onSessionTerminated: () => void,
): void {
  audioTrack.onended = () => {
    streamer.gracefulDisconnect("USER_STOPPED");
    onSessionTerminated();
  };
}
```

- [ ] **Step 4: Run, expect pass; lint and type-check**

```bash
npx -y pnpm@10.33.2 --filter frontend test
npx -y pnpm@10.33.2 --filter frontend lint
npx -y pnpm@10.33.2 --filter frontend exec tsc --noEmit
```

Expected: all pass. If the reconnect-sequence test's fake-timer arithmetic is off by one attempt, fix the test's expectation only if the production behaviour matches the Global Constraints (delays 1 s, 2 s, 4 s, then stop); otherwise fix the code.

- [ ] **Step 5: Commit (only after the user authorizes)**

```bash
git add frontend/lib/audio/streamer.ts frontend/lib/audio/streamer.test.ts
git commit -m "feat(audio): add binary WebSocket streamer with handshake, backpressure and reconnect"
```

---

### Task 6: `/spike` test page (ECHO-18 task 4 UI, ECHO-19 manual test)

**Files:**
- Modify (replace stub): `frontend/app/spike/page.tsx`

**Interfaces:**
- Consumes: `AudioCapture`, `AudioCaptureError` from `@/lib/audio/capture`; `EchoAudioStreamer`, `attachMeetingLifecycle`, `ConnectionState` from `@/lib/audio/streamer`.
- Produces: a page with Start/Stop buttons, a volume meter, connection state and a readable error line. No new exports.

- [ ] **Step 1: Read the Next.js guidance**

Per `frontend/AGENTS.md`, skim the client-component and `app/` page docs under `frontend/node_modules/next/dist/docs/` and note anything that contradicts the code below (the page needs only `"use client"`, `useState`, `useRef`).

- [ ] **Step 2: Replace the page**

`frontend/app/spike/page.tsx`:

```tsx
"use client";

import { useRef, useState } from "react";
import { AudioCapture, AudioCaptureError } from "@/lib/audio/capture";
import { EchoAudioStreamer, type ConnectionState } from "@/lib/audio/streamer";

const WS_URL = process.env.NEXT_PUBLIC_BACKEND_WS_URL ?? "ws://localhost:8000/ws/audio";

const ERROR_TEXT: Record<string, string> = {
  NO_AUDIO_TRACK: "No audio was shared. Pick the meeting tab and tick 'Share tab audio'.",
  PERMISSION_DENIED: "Sharing was cancelled or denied. Try again.",
  UNSUPPORTED: "This browser cannot capture tab audio. Use Chrome or Edge.",
};

export default function AudioSpikePage() {
  const [running, setRunning] = useState(false);
  const [level, setLevel] = useState(0);
  const [connection, setConnection] = useState<ConnectionState>("DISCONNECTED");
  const [sent, setSent] = useState(0);
  const [dropped, setDropped] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const captureRef = useRef<AudioCapture | null>(null);
  const streamerRef = useRef<EchoAudioStreamer | null>(null);

  const start = async () => {
    setError(null);
    setSent(0);
    setDropped(0);
    const streamer = new EchoAudioStreamer(WS_URL, crypto.randomUUID(), {
      onStateChange: setConnection,
    });
    const capture = new AudioCapture({
      onAudioChunk: (chunk) => {
        if (streamer.sendAudioChunk(chunk)) setSent((n) => n + 1);
        else setDropped((n) => n + 1);
      },
      onLevel: setLevel,
      onEnded: () => {
        streamer.gracefulDisconnect("USER_STOPPED");
        setRunning(false);
        setLevel(0);
      },
    });
    try {
      await streamer.connect();
      await capture.start();
      streamerRef.current = streamer;
      captureRef.current = capture;
      setRunning(true);
    } catch (err) {
      streamer.gracefulDisconnect("ERROR");
      setError(
        err instanceof AudioCaptureError
          ? (ERROR_TEXT[err.code] ?? err.message)
          : "Could not reach the ECHO backend. Is it running?",
      );
    }
  };

  const stop = async () => {
    streamerRef.current?.gracefulDisconnect("USER_STOPPED");
    await captureRef.current?.stop();
    streamerRef.current = null;
    captureRef.current = null;
    setRunning(false);
    setLevel(0);
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">ECHO audio capture spike</h1>
      <p className="text-sm text-zinc-600">
        Share the meeting tab with audio. Chunks of 100 ms (3200 bytes) stream to {WS_URL}.
      </p>

      <div className="flex gap-3">
        <button
          onClick={start}
          disabled={running}
          className="rounded-lg bg-blue-600 px-5 py-2 font-medium text-white disabled:bg-zinc-400"
        >
          Start
        </button>
        <button
          onClick={stop}
          disabled={!running}
          className="rounded-lg bg-red-600 px-5 py-2 font-medium text-white disabled:bg-zinc-400"
        >
          Stop
        </button>
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}

      <section className="rounded-lg border p-4 text-sm">
        <div className="mb-3 flex items-center justify-between">
          <span>Connection</span>
          <span className="font-mono">{connection}</span>
        </div>
        <div className="mb-1">Level</div>
        <div className="h-2 w-full overflow-hidden rounded bg-zinc-200">
          <div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, level * 300)}%` }} />
        </div>
        <div className="mt-3 flex justify-between font-mono">
          <span>sent {sent}</span>
          <span>dropped {dropped}</span>
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Lint, type-check and build**

```bash
npx -y pnpm@10.33.2 --filter frontend lint
npx -y pnpm@10.33.2 --filter frontend exec tsc --noEmit
npx -y pnpm@10.33.2 --filter frontend build
```

Expected: all clean; the build lists `/spike`. If React's lint rules flag a pattern (for example state updates in callbacks), fix the page, do not disable the rule.

- [ ] **Step 4: Manual smoke test (record the outcome, do not claim it passed if skipped)**

In one shell run the backend (`cd backend && .venv/Scripts/fastapi dev app/main.py`); in another run `npx -y pnpm@10.33.2 --filter frontend dev`. Open `http://localhost:3000/spike` in Chrome, press Start, choose a tab playing audio with "Share tab audio" ticked, and confirm the `sent` counter climbs at about 10 per second and the level bar moves. Press Chrome's "Stop sharing" and confirm the page returns to idle. If no Chrome is available, state in the PR that this step was not run.

- [ ] **Step 5: Commit (only after the user authorizes)**

```bash
git add frontend/app/spike/page.tsx
git commit -m "feat(audio): wire capture and streamer into the /spike test page"
```

---

### Task 7: Extension HUD component and waveform (ECHO-21 tasks 1 to 3)

**Files:**
- Create: `extension/manifest.json`, `extension/src/hud.js`, `extension/test/hud.test.js`

**Interfaces:**
- Produces (classic script, no modules):
  - `globalThis.EchoSentry.EchoSentryHud` (a custom element registered as `<echo-sentry-hud>`) with methods `attachAnalyser(analyser: AnalyserNode): void`, `detachAnalyser(): void`, getter `live: boolean`, and a closed set of states: standby (no analyser) or `LIVE MONITORING` (analyser attached).
  - `globalThis.EchoSentry.BAR_COUNT = 12`.
  - CommonJS export of the same object when `module` exists (so vitest can `require` it).
- Shadow root is `open`; the canvas is `#waveform-canvas` inside it.

- [ ] **Step 1: Write failing tests**

`extension/test/hud.test.js`:

```js
import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const { EchoSentryHud, BAR_COUNT } = require("../src/hud.js");

let rafCallbacks;
let drawn;

function fakeAnalyser(values) {
  return {
    fftSize: 0,
    frequencyBinCount: 32,
    getByteFrequencyData: (arr) => arr.set(values.slice(0, arr.length)),
  };
}

beforeEach(() => {
  rafCallbacks = new Map();
  let id = 0;
  vi.stubGlobal("requestAnimationFrame", (cb) => {
    rafCallbacks.set(++id, cb);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (n) => rafCallbacks.delete(n));
  drawn = [];
  HTMLCanvasElement.prototype.getContext = () => ({
    clearRect: () => {},
    fillRect: (x, y, w, h) => drawn.push({ x, y, w, h }),
    beginPath: () => {},
    fill: () => {},
    set fillStyle(_v) {},
  });
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function mount() {
  const hud = document.createElement("echo-sentry-hud");
  document.body.appendChild(hud);
  return hud;
}

function frame() {
  const [[id, cb]] = [...rafCallbacks.entries()];
  rafCallbacks.delete(id);
  cb(0);
}

describe("Shadow DOM isolation", () => {
  it("keeps the canvas inside the shadow root, invisible to the page", () => {
    const hud = mount();
    expect(hud.shadowRoot.querySelector("#waveform-canvas")).not.toBeNull();
    expect(document.querySelector("#waveform-canvas")).toBeNull();
  });

  it("shows the brand, standby state and no pulsing dot colour of live", () => {
    const hud = mount();
    const text = hud.shadowRoot.textContent;
    expect(text).toContain("ECHO Sentry");
    expect(text).toContain("STANDBY");
    expect(text).not.toContain("LIVE MONITORING");
    expect(hud.live).toBe(false);
  });

  it("does not build the shadow DOM twice when re-attached", () => {
    const hud = mount();
    document.body.removeChild(hud);
    document.body.appendChild(hud);
    expect(hud.shadowRoot.querySelectorAll("canvas")).toHaveLength(1);
  });
});

describe("analyser binding", () => {
  it("switches to LIVE MONITORING and configures fftSize 64", () => {
    const hud = mount();
    const analyser = fakeAnalyser(new Array(32).fill(0));
    hud.attachAnalyser(analyser);
    expect(analyser.fftSize).toBe(64);
    expect(hud.live).toBe(true);
    expect(hud.shadowRoot.textContent).toContain("LIVE MONITORING");
  });

  it("draws a 2 px floor in silence and up to 20 px for loud input", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    frame();
    expect(drawn).toHaveLength(BAR_COUNT);
    expect(drawn.every((b) => b.h === 2)).toBe(true);

    drawn.length = 0;
    hud.detachAnalyser();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(255)));
    frame();
    expect(drawn.every((b) => b.h === 20)).toBe(true);
  });

  it("scales bars with amplitude between the floor and the max", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(128)));
    frame();
    const h = drawn[0].h;
    expect(h).toBeGreaterThan(2);
    expect(h).toBeLessThan(20);
  });

  it("keeps drawing every frame while attached", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(10)));
    frame();
    expect(rafCallbacks.size).toBe(1);
    frame();
    expect(rafCallbacks.size).toBe(1);
  });
});

describe("render loop cleanup", () => {
  it("cancels the animation frame when the analyser is detached", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    expect(rafCallbacks.size).toBe(1);
    hud.detachAnalyser();
    expect(rafCallbacks.size).toBe(0);
    expect(hud.live).toBe(false);
  });

  it("cancels the animation frame when the element is removed", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    hud.remove();
    expect(rafCallbacks.size).toBe(0);
  });

  it("does not start a second loop when attached twice", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    expect(rafCallbacks.size).toBe(1);
  });

  it("survives a canvas without a 2d context", () => {
    HTMLCanvasElement.prototype.getContext = () => null;
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    expect(() => frame()).not.toThrow();
  });
});
```

- [ ] **Step 2: Run, expect failure**

Run: `npx -y pnpm@10.33.2 --filter frontend test`
Expected: FAIL, cannot find `extension/src/hud.js` (and, if the include glob was wrong in Task 3, fix it now).

- [ ] **Step 3: Implement the HUD and manifest**

`extension/src/hud.js`:

```js
(function () {
  const BAR_COUNT = 12;
  const BAR_WIDTH = 3;
  const BAR_GAP = 2;
  const MIN_BAR = 2;
  const ACCENT = "#10b981";

  const TEMPLATE = `
    <style>
      :host {
        position: fixed; top: 16px; right: 16px; z-index: 2147483647;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }
      .hud-card {
        display: flex; align-items: center; gap: 12px;
        background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(8px);
        border: 1px solid rgba(51, 65, 85, 0.8); padding: 8px 14px;
        border-radius: 9999px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
        color: #f8fafc;
      }
      .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #64748b; }
      :host([live]) .status-dot { background: ${ACCENT}; box-shadow: 0 0 10px ${ACCENT}; animation: pulse 1.5s infinite; }
      .meta-text { display: flex; flex-direction: column; }
      .title { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #94a3b8; }
      .status { font-size: 12px; font-weight: 600; color: #f1f5f9; }
      canvas { width: 60px; height: 20px; }
      @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } }
    </style>
    <div class="hud-card">
      <div class="status-dot"></div>
      <div class="meta-text">
        <span class="title">ECHO Sentry</span>
        <span class="status" id="status-text">STANDBY</span>
      </div>
      <canvas id="waveform-canvas" width="60" height="20"></canvas>
    </div>
  `;

  class EchoSentryHud extends HTMLElement {
    constructor() {
      super();
      this._analyser = null;
      this._data = null;
      this._raf = 0;
    }

    connectedCallback() {
      if (!this.shadowRoot) {
        this.attachShadow({ mode: "open" }).innerHTML = TEMPLATE;
      }
      if (this._analyser) this._startLoop();
    }

    disconnectedCallback() {
      this._stopLoop();
    }

    get live() {
      return this._analyser !== null;
    }

    attachAnalyser(analyser) {
      analyser.fftSize = 64;
      this._analyser = analyser;
      this._data = new Uint8Array(analyser.frequencyBinCount);
      this.setAttribute("live", "");
      this._setStatus("LIVE MONITORING");
      this._stopLoop();
      if (this.isConnected) this._startLoop();
    }

    detachAnalyser() {
      this._stopLoop();
      this._analyser = null;
      this._data = null;
      this.removeAttribute("live");
      this._setStatus("STANDBY");
    }

    _setStatus(text) {
      const el = this.shadowRoot && this.shadowRoot.getElementById("status-text");
      if (el) el.textContent = text;
    }

    _startLoop() {
      if (this._raf) return;
      const tick = () => {
        this._raf = requestAnimationFrame(tick);
        this._draw();
      };
      this._raf = requestAnimationFrame(tick);
    }

    _stopLoop() {
      if (this._raf) {
        cancelAnimationFrame(this._raf);
        this._raf = 0;
      }
    }

    _draw() {
      const canvas = this.shadowRoot && this.shadowRoot.getElementById("waveform-canvas");
      const ctx = canvas && canvas.getContext("2d");
      if (!ctx || !this._analyser) return;
      this._analyser.getByteFrequencyData(this._data);

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = ACCENT;
      let x = 1;
      for (let i = 0; i < BAR_COUNT; i++) {
        const level = (this._data[i] || 0) / 255;
        const h = Math.max(MIN_BAR, Math.round(canvas.height * level));
        ctx.fillRect(x, (canvas.height - h) / 2, BAR_WIDTH, h);
        x += BAR_WIDTH + BAR_GAP;
      }
    }
  }

  if (typeof customElements !== "undefined" && !customElements.get("echo-sentry-hud")) {
    customElements.define("echo-sentry-hud", EchoSentryHud);
  }

  const api = { EchoSentryHud, BAR_COUNT };
  globalThis.EchoSentry = Object.assign(globalThis.EchoSentry || {}, api);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
```

`extension/manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "ECHO In-Meeting Defense Extension",
  "version": "1.0.0",
  "description": "Shows live ECHO Sentry monitoring status on Google Meet.",
  "permissions": ["tabCapture", "activeTab"],
  "action": { "default_title": "Start ECHO monitoring on this tab" },
  "background": { "service_worker": "background.js" },
  "content_scripts": [
    {
      "matches": ["https://meet.google.com/*"],
      "js": ["src/hud.js", "src/meet.js", "content.js"],
      "run_at": "document_idle"
    }
  ]
}
```

(`fillStyle` is set before the loop because the colour never changes; the test's `set fillStyle` accessor accepts it.)

- [ ] **Step 4: Run, expect pass**

Run: `npx -y pnpm@10.33.2 --filter frontend test`
Expected: all HUD tests pass along with earlier suites. If jsdom rejects `attachShadow`/`customElements`, record the jsdom version and fix the test setup, not the HUD semantics.

- [ ] **Step 5: Commit (only after the user authorizes)**

```bash
git add extension/manifest.json extension/src/hud.js extension/test/hud.test.js
git commit -m "feat(extension): add Shadow DOM sentry HUD with live waveform"
```

---

### Task 8: Meet lifecycle, tab-audio glue, background worker (ECHO-21 task 4)

**Files:**
- Create: `extension/src/meet.js`, `extension/content.js`, `extension/background.js`, `extension/test/meet.test.js`

**Interfaces:**
- Consumes: `globalThis.EchoSentry.EchoSentryHud` from `hud.js`.
- Produces:
  - `EchoSentry.isMeetRoomUrl(url: string): boolean` (true only for `https://meet.google.com/abc-defg-hij` with optional path/query/hash after it).
  - `EchoSentry.createMeetLifecycle({ getUrl, onEnter, onLeave, intervalMs? }): { stop(): void }` which calls `onEnter` once when the URL becomes a room URL and `onLeave` once when it stops being one; it polls `getUrl` (Meet is a single-page app and fires no reload) and also checks on `popstate`/`hashchange`.
  - Message `{ type: "ECHO_STREAM_ID", streamId: string }` from `background.js` to the tab's content script.

- [ ] **Step 1: Write failing tests**

`extension/test/meet.test.js`:

```js
import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const { isMeetRoomUrl, createMeetLifecycle } = require("../src/meet.js");

describe("isMeetRoomUrl", () => {
  it.each([
    "https://meet.google.com/abc-defg-hij",
    "https://meet.google.com/abc-defg-hij?authuser=1",
    "https://meet.google.com/abc-defg-hij/",
    "https://meet.google.com/abc-defg-hij#x",
  ])("accepts %s", (url) => expect(isMeetRoomUrl(url)).toBe(true));

  it.each([
    "https://meet.google.com/",
    "https://meet.google.com/landing",
    "https://meet.google.com/abc-defg-hijk",
    "https://meet.google.com/ab-defg-hij",
    "https://meet.google.com/ABC-DEFG-HIJ",
    "http://meet.google.com/abc-defg-hij",
    "https://evil.example/meet.google.com/abc-defg-hij",
    "https://meet.google.com.evil.example/abc-defg-hij",
    "",
  ])("rejects %s", (url) => expect(isMeetRoomUrl(url)).toBe(false));

  it("tolerates non-string input", () => {
    expect(isMeetRoomUrl(undefined)).toBe(false);
    expect(isMeetRoomUrl(null)).toBe(false);
  });
});

describe("createMeetLifecycle", () => {
  let url;
  beforeEach(() => {
    vi.useFakeTimers();
    url = "https://meet.google.com/landing";
  });
  afterEach(() => vi.useRealTimers());

  const make = () => {
    const onEnter = vi.fn();
    const onLeave = vi.fn();
    const life = createMeetLifecycle({ getUrl: () => url, onEnter, onLeave, intervalMs: 500 });
    return { life, onEnter, onLeave };
  };

  it("does nothing on a non-room page", () => {
    const { onEnter, onLeave } = make();
    vi.advanceTimersByTime(5000);
    expect(onEnter).not.toHaveBeenCalled();
    expect(onLeave).not.toHaveBeenCalled();
  });

  it("enters immediately if the page already is a room", () => {
    url = "https://meet.google.com/abc-defg-hij";
    const { onEnter } = make();
    expect(onEnter).toHaveBeenCalledTimes(1);
  });

  it("enters once when navigating into a room and leaves once when navigating out", () => {
    const { onEnter, onLeave } = make();
    url = "https://meet.google.com/abc-defg-hij";
    vi.advanceTimersByTime(500);
    vi.advanceTimersByTime(2000);
    expect(onEnter).toHaveBeenCalledTimes(1);
    url = "https://meet.google.com/landing";
    vi.advanceTimersByTime(500);
    vi.advanceTimersByTime(2000);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("re-enters for a second meeting", () => {
    const { onEnter, onLeave } = make();
    url = "https://meet.google.com/abc-defg-hij";
    vi.advanceTimersByTime(500);
    url = "https://meet.google.com/landing";
    vi.advanceTimersByTime(500);
    url = "https://meet.google.com/xyz-abcd-efg";
    vi.advanceTimersByTime(500);
    expect(onEnter).toHaveBeenCalledTimes(2);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("stop() halts polling and leaves an active room exactly once", () => {
    url = "https://meet.google.com/abc-defg-hij";
    const { life, onLeave } = make();
    life.stop();
    life.stop();
    vi.advanceTimersByTime(5000);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run, expect failure**

Run: `npx -y pnpm@10.33.2 --filter frontend test`
Expected: FAIL, cannot find `extension/src/meet.js`.

- [ ] **Step 3: Implement the lifecycle helper**

`extension/src/meet.js`:

```js
(function () {
  const ROOM_RE = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?#].*)?$/;

  function isMeetRoomUrl(url) {
    return typeof url === "string" && ROOM_RE.test(url);
  }

  // Meet is a single-page app: leaving a call changes the URL without a reload,
  // so we watch the URL instead of waiting for page events.
  function createMeetLifecycle({ getUrl, onEnter, onLeave, intervalMs = 500 }) {
    let inRoom = false;
    let timer = null;

    function check() {
      const now = isMeetRoomUrl(getUrl());
      if (now && !inRoom) {
        inRoom = true;
        onEnter();
      } else if (!now && inRoom) {
        inRoom = false;
        onLeave();
      }
    }

    function stop() {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
        if (typeof window !== "undefined") {
          window.removeEventListener("popstate", check);
          window.removeEventListener("hashchange", check);
        }
      }
      if (inRoom) {
        inRoom = false;
        onLeave();
      }
    }

    check();
    timer = setInterval(check, intervalMs);
    if (typeof window !== "undefined") {
      window.addEventListener("popstate", check);
      window.addEventListener("hashchange", check);
    }
    return { stop };
  }

  const api = { isMeetRoomUrl, createMeetLifecycle };
  globalThis.EchoSentry = Object.assign(globalThis.EchoSentry || {}, api);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
```

- [ ] **Step 4: Run, expect pass**

Run: `npx -y pnpm@10.33.2 --filter frontend test`
Expected: all pass.

- [ ] **Step 5: Write the glue (not unit-tested; it needs a real browser)**

`extension/background.js`:

```js
// Clicking the toolbar icon grants activeTab and lets us ask Chrome for a
// capture id for that tab. The content script on the page consumes it.
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;
  try {
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
    await chrome.tabs.sendMessage(tab.id, { type: "ECHO_STREAM_ID", streamId });
  } catch (err) {
    console.warn("[ECHO] Could not start tab capture:", err);
  }
});
```

`extension/content.js`:

```js
(function () {
  const { createMeetLifecycle } = globalThis.EchoSentry;

  let hud = null;
  let audio = null; // { ctx, stream }

  function mountHud() {
    if (hud) return;
    hud = document.createElement("echo-sentry-hud");
    document.documentElement.appendChild(hud);
  }

  async function releaseAudio() {
    if (!audio) return;
    const { ctx, stream } = audio;
    audio = null;
    stream.getTracks().forEach((t) => t.stop());
    await ctx.close().catch(() => undefined);
  }

  async function unmountHud() {
    if (hud) {
      hud.detachAnalyser();
      hud.remove(); // disconnectedCallback also cancels the render loop
      hud = null;
    }
    await releaseAudio();
  }

  async function attachTabAudio(streamId) {
    if (!hud) return;
    await releaseAudio();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
    });
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    source.connect(analyser);
    // Capturing a tab mutes it for the user; route it back to the speakers.
    source.connect(ctx.destination);
    audio = { ctx, stream };
    stream.getAudioTracks()[0].onended = () => {
      if (hud) hud.detachAnalyser();
      void releaseAudio();
    };
    hud.attachAnalyser(analyser);
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.type === "ECHO_STREAM_ID" && typeof message.streamId === "string") {
      attachTabAudio(message.streamId).catch((err) => console.warn("[ECHO] Tab audio failed:", err));
    }
  });

  createMeetLifecycle({
    getUrl: () => location.href,
    onEnter: mountHud,
    onLeave: () => void unmountHud(),
  });
})();
```

- [ ] **Step 6: Re-run the suite and syntax-check the glue**

```bash
npx -y pnpm@10.33.2 --filter frontend test
node --check extension/content.js
node --check extension/background.js
```

Expected: tests pass; both `node --check` calls print nothing.

- [ ] **Step 7: Commit (only after the user authorizes)**

```bash
git add extension
git commit -m "feat(extension): mount HUD on Meet rooms and bind tab audio to the waveform"
```

---

### Task 9: Docs, CI and final verification

**Files:**
- Modify: `README.md`, `backend/README.md`, `.github/workflows/ci.yml`
- Create: `extension/README.md`

- [ ] **Step 1: Add the extension README**

`extension/README.md`: how to load it (`chrome://extensions` → Developer mode → Load unpacked → select `extension/`), how to use it (open a Google Meet room, the HUD appears in standby; click the toolbar icon to start tab capture and the HUD goes to `LIVE MONITORING`), and the known gap: the extension shows the waveform only; streaming its audio to `/ws/audio` reuses the `frontend/lib/audio` modules and needs a bundling step that is not part of this feature.

- [ ] **Step 2: Document the protocol and commands**

In `backend/README.md` replace the "Audio Streaming Endpoint" text with the protocol from Global Constraints (handshake first, binary 16 kHz PCM frames, `STOP_STREAM`, close codes 1000 / 1008 / 1009, no acks, zero retention, 5 s ring buffer) and the backend test command. In the root `README.md`, replace the "Audio Streaming Spike" bullet with a short description of `/spike` and `extension/`, and add `pnpm --filter frontend test` to the commands.

- [ ] **Step 3: Run the tests in CI**

In `.github/workflows/ci.yml`, add after "Lint Frontend": a step `Test Frontend` running `pnpm --filter frontend test`; and in the backend job after the flake8 step: a step `Test Backend` running `python -m pytest tests -q`.

- [ ] **Step 4: Full verification (read every output)**

```bash
cd backend && .venv/Scripts/python -m pytest tests -q && .venv/Scripts/python -m flake8 app tests --count --select=E9,F63,F7,F82 --statistics
cd .. && npx -y pnpm@10.33.2 --filter frontend test
npx -y pnpm@10.33.2 --filter frontend lint
npx -y pnpm@10.33.2 --filter frontend exec tsc --noEmit
npx -y pnpm@10.33.2 --filter frontend build
```

Expected: every command succeeds. Record the pass counts.

- [ ] **Step 5: Commit (only after the user authorizes)**

```bash
git add README.md backend/README.md extension/README.md .github/workflows/ci.yml
git commit -m "docs(audio): document Feature 1 protocol and run tests in CI"
```

---

## Self-Review

- **ECHO-18:** FR-1/2 (getDisplayMedia, missing "Share audio" error) → Task 4 `initDisplayMediaStream` + tests; FR-3 (stop video tracks) → Task 4; FR-4 (16 kHz) → `AudioContext({sampleRate})` plus `Downsampler`, Tasks 3 and 4; FR-5 (mono average) → worklet, Task 4; FR-6 (Float32→Int16) and FR-7 (100 ms chunks) → Task 3; ticket Task 4 (`onAudioChunk`, RMS) → `AudioCapture` options, Task 4. NFR-1/3 (50 ms, 5% CPU) and the 10-minute leak criterion need a real browser: not covered by automated tests, listed under Not Verified. The ticket's PCM, downsample (480→160) and chunk-size unit tests are Task 3.
- **ECHO-19:** FR-1 (states, reconnect) → Task 5; FR-2 (handshake first) → Task 5 tests; FR-3 (binary) → `binaryType` test; FR-4 (64 KB drop) → tests; FR-5 (`track.onended` → `STOP_STREAM`, 1000) → `attachMeetingLifecycle` test. NFR-3 (3 retries 1/2/4 s) → reconnect test. NFR-1/2 (30 ms latency, 32 KB/s) are runtime properties checked in the Task 6 manual run.
- **ECHO-20:** FR-1/2 → Task 2; FR-3 (5 s ring, overwrite) → Task 1; FR-4 (zero retention) → `test_zero_retention_no_files_written`; FR-5 (stream interface, sliding window hook) → `vertex_ai_stream_generator` and `get_latest_window`. NFR-1 (5 ms) and NFR-2 (under 5 MB per session: 160 KB buffer plus a 100-slot queue of 3.2 KB chunks is about 0.5 MB) hold by construction; no timing test. NFR-3 (thread safety): everything runs on the single asyncio loop, so no locks; stated here, not tested. The Cloud Run `--session-affinity` flag is deployment config and out of this plan.
- **ECHO-21:** FR-1 (injection, Shadow DOM) → Tasks 7 and 8; FR-2 (layout, pulsing dot) → HUD template; FR-3 (analyser, fftSize 64, 12 bars, 2 to 20 px) → HUD tests; FR-4 (lifecycle sync) → `createMeetLifecycle` and `content.js`. Contradictions in the ticket resolved by ruling: FR-3 says 10 to 14 bars but the sample code draws 8 (12 chosen); FR-1 says inject on entering the room but FR-4 says appear when audio is active (HUD mounts in STANDBY on entry and switches to LIVE MONITORING when the analyser attaches). NFR-1 (60 fps) is `requestAnimationFrame` by design, unmeasured.
- **Placeholder scan:** none; every code step has full code.
- **Type consistency:** `Downsampler`, `PcmChunker`, `AudioCapture`, `EchoAudioStreamer`, `AudioSessionContext`, `registry` and the HUD's `attachAnalyser`/`detachAnalyser` names match across tasks.
- **Review Focus coverage:** items 1 to 3 → Task 2 tests; item 4 → Task 5 test; item 5 → Task 4 tests.

## Not verified by this plan's automated checks
- Real Chrome behaviour: `getDisplayMedia` audio, AudioWorklet timing, `chrome.tabCapture` and `getUserMedia` with a tab stream id, and the live Meet DOM. These need a manual run (Task 6 Step 4, extension README).
- The extension cannot yet stream audio to the backend (see `extension/README.md`).
- Wiring `AudioSessionContext.vertex_ai_stream_generator()` into `GeminiLiveClient` waits until this branch and PR #2 (ECHO-22) are both merged.
