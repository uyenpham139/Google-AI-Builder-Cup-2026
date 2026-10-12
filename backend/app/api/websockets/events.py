"""Event channel for the Meet extension and the ERP portal (ECHO-25)."""
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.intervention import runtime

logger = logging.getLogger(__name__)
router = APIRouter()

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_EVENT_SOCKETS = 500  # unauthenticated endpoint: bound open connections
MAX_SOCKETS_PER_SESSION = 10  # one session id cannot use up the whole budget


@router.websocket("/ws/events")
async def events_endpoint(websocket: WebSocket):
    session_id = websocket.query_params.get("sessionId", "")
    await websocket.accept()
    if not SESSION_ID_RE.match(session_id):
        await websocket.close(code=1008)
        return
    if runtime.broadcast.total() >= MAX_EVENT_SOCKETS or runtime.broadcast.count(session_id) >= MAX_SOCKETS_PER_SESSION:
        await websocket.close(code=1013)
        return

    # A client that joins after the lock is told immediately (inside attach).
    await runtime.lockdown.attach(session_id, websocket)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break  # this channel is server-to-client only: anything received is ignored
    except WebSocketDisconnect:
        pass
    finally:
        runtime.broadcast.unregister(session_id, websocket)
