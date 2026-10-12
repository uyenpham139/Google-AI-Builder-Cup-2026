"""Multi-client fan-out by session id (ECHO-25)."""
import asyncio
import json
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TextSocket(Protocol):
    async def send_text(self, data: str) -> None: ...


class SessionBroadcastManager:
    def __init__(self):
        self._sockets: dict[str, list[TextSocket]] = {}

    def register(self, session_id: str, socket: TextSocket) -> None:
        self._sockets.setdefault(session_id, []).append(socket)

    def unregister(self, session_id: str, socket: TextSocket) -> None:
        sockets = self._sockets.get(session_id)
        if not sockets or socket not in sockets:
            return
        sockets.remove(socket)
        if not sockets:
            del self._sockets[session_id]

    def count(self, session_id: str) -> int:
        return len(self._sockets.get(session_id, []))

    def total(self) -> int:
        return sum(len(s) for s in self._sockets.values())

    async def send_one(self, session_id: str, socket: TextSocket, payload: dict[str, Any]) -> bool:
        try:
            await socket.send_text(json.dumps(payload))
            return True
        except Exception as exc:
            logger.warning("Dropping dead event socket for %s: %s", session_id, exc)
            self.unregister(session_id, socket)
            return False

    async def broadcast(self, session_id: str, payload: dict[str, Any]) -> int:
        """Send to every client of the session at once. Returns how many received it."""
        sockets = list(self._sockets.get(session_id, []))
        if not sockets:
            return 0
        results = await asyncio.gather(*(self.send_one(session_id, s, payload) for s in sockets))
        return sum(results)
