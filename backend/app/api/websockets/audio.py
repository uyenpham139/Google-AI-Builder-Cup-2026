import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ingestion.protocol import InitSession, ProtocolError, StopStream, parse_control
from app.services.ingestion.registry import registry
from app.services.ingestion.session import AudioSessionContext

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FRAME_BYTES = 64 * 1024
MAX_SESSIONS = 100  # unauthenticated endpoint: bound total RAM
INIT_TIMEOUT_S = 10.0  # a socket that never sends INIT_SESSION is dropped


async def _close_quietly(websocket: WebSocket, code: int) -> None:
    with contextlib.suppress(RuntimeError):
        await websocket.close(code=code)


@router.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    session: AudioSessionContext | None = None
    close_code: int | None = 1000

    try:
        while True:
            try:
                if session is None:
                    message = await asyncio.wait_for(websocket.receive(), INIT_TIMEOUT_S)
                else:
                    message = await websocket.receive()
            except asyncio.TimeoutError:
                logger.warning("No INIT_SESSION within %.0fs", INIT_TIMEOUT_S)
                close_code = 1008
                break
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
                    if len(registry) >= MAX_SESSIONS and registry.get(control.session_id) is None:
                        close_code = 1013  # try again later
                        break
                    session = AudioSessionContext(control.session_id)
                    session.on_replaced = lambda: asyncio.ensure_future(_close_quietly(websocket, 1008))
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
