import asyncio
import base64
import contextlib
import json
import logging
import re
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.prompts.intervenor_prompt import build_intervenor_prompt, new_trigger_token
from app.services.gemini_live.client import GeminiLiveClient, GeminiLiveError
from app.services.intervention import runtime

# from app.agents.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

STOP_STREAM = "STOP_STREAM"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
DOWNLINK_SAMPLE_RATE = 24000


def _is_stop(text: str) -> bool:
    try:
        payload = json.loads(text)
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("type") == STOP_STREAM


@router.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected to audio stream")

    session_id = websocket.query_params.get("sessionId", "")
    if not SESSION_ID_RE.match(session_id):
        session_id = uuid.uuid4().hex
    token = new_trigger_token()
    send_lock = asyncio.Lock()  # acks and downlink audio share one socket

    async def forward_audio(pcm: bytes) -> None:
        if not runtime.live_sessions.is_armed(session_id, client):
            return  # no trigger was sent: whatever the model says is not an intervention
        frame = {"type": "BARGE_IN_AUDIO", "audio": base64.b64encode(pcm).decode(), "sampleRate": DOWNLINK_SAMPLE_RATE}
        async with send_lock:
            await websocket.send_text(json.dumps(frame))

    client = GeminiLiveClient(system_instruction=build_intervenor_prompt(token), on_audio=forward_audio)
    try:
        await client.connect()
    except GeminiLiveError as exc:
        logger.error("Could not start Gemini Live session: %s", exc)
        await websocket.close(code=1011)
        return

    if not runtime.live_sessions.register(session_id, client, token):
        logger.warning("Session id %s is already live; refusing a second connection", session_id)
        await client.disconnect()
        await websocket.close(code=1008)
        return
    close_code = 1000
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                close_code = None
                break
            if message.get("bytes") is not None:
                chunk = message["bytes"]
                forwarded = await client.send_audio(chunk)
                async with send_lock:
                    await websocket.send_text(
                        json.dumps({"status": "received", "bytes": len(chunk), "forwarded": forwarded})
                    )
                if client.failed:
                    close_code = 1011
                    break
            elif message.get("text") is not None and _is_stop(message["text"]):
                logger.info("STOP_STREAM received")
                break
    except WebSocketDisconnect:
        close_code = None  # browser left mid-send
    finally:
        runtime.live_sessions.remove(session_id, client)
        await client.disconnect()
        if close_code is not None:
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=close_code)
        logger.info("Audio stream closed")
