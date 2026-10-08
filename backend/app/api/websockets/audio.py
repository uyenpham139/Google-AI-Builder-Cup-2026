import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.gemini_live.client import GeminiLiveClient, GeminiLiveError

# from app.agents.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

STOP_STREAM = "STOP_STREAM"


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

    client = GeminiLiveClient()
    try:
        await client.connect()
    except GeminiLiveError as exc:
        logger.error("Could not start Gemini Live session: %s", exc)
        await websocket.close(code=1011)
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
        await client.disconnect()
        if close_code is not None:
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=close_code)
        logger.info("Audio stream closed")
