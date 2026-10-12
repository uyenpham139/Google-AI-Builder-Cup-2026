"""Risk gate and dual-channel lockdown (ECHO-23 trigger + ECHO-25 broadcast)."""
import asyncio
import logging
import math
import time
from typing import Any

from app.services.intervention.broadcast import SessionBroadcastManager, TextSocket
from app.services.intervention.incidents import IncidentLogger
from app.services.intervention.triggers import TextTurnSender, inject_barge_in_trigger

logger = logging.getLogger(__name__)

RISK_THRESHOLD = 0.85
LOG_TIMEOUT_S = 2.0  # a slow audit write must not hold up the caller


class LiveSessionRegistry:
    """Maps a session id to its Live client and the trigger token baked into its prompt.

    A session is `armed` only after its barge-in trigger was delivered; until then model
    audio is not forwarded, so the model cannot reach the user without a real trigger.
    """

    def __init__(self):
        self._live: dict[str, tuple[TextTurnSender, str]] = {}
        self._armed: set[str] = set()

    def register(self, session_id: str, client: TextTurnSender, token: str) -> bool:
        """Returns False when the id is already live: a second connection must not take it over."""
        if session_id in self._live:
            return False
        self._live[session_id] = (client, token)
        return True

    def get(self, session_id: str) -> tuple[TextTurnSender, str] | None:
        return self._live.get(session_id)

    def arm(self, session_id: str) -> None:
        self._armed.add(session_id)

    def disarm(self, session_id: str) -> None:
        self._armed.discard(session_id)

    def is_armed(self, session_id: str, client: TextTurnSender) -> bool:
        entry = self._live.get(session_id)
        return entry is not None and entry[0] is client and session_id in self._armed

    def remove(self, session_id: str, client: TextTurnSender) -> None:
        entry = self._live.get(session_id)
        if entry is not None and entry[0] is client:
            del self._live[session_id]
            self._armed.discard(session_id)


class LockdownService:
    def __init__(self, broadcast: SessionBroadcastManager, incidents: IncidentLogger, live: LiveSessionRegistry):
        self._broadcast = broadcast
        self._incidents = incidents
        self._live = live
        self._locks: dict[str, dict[str, Any]] = {}
        self._speaking: set[str] = set()
        self._spoken: set[str] = set()

    def is_locked(self, session_id: str) -> bool:
        return session_id in self._locks

    async def attach(self, session_id: str, socket: TextSocket) -> None:
        """Register a client; one that joins after the lock is locked on the spot."""
        self._broadcast.register(session_id, socket)
        payload = self._locks.get(session_id)
        if payload is not None:
            await self._broadcast.send_one(session_id, socket, payload)

    async def lock_session(
        self, session_id: str, risk_score: float, reason: str, acoustic_flag: str | None = None
    ) -> dict[str, Any] | None:
        """Freeze the session once. Returns the broadcast payload, or None if it was already locked."""
        if session_id in self._locks:
            return None
        payload = {
            "type": "LOCK_SESSION",
            "sessionId": session_id,
            "riskScore": risk_score,
            "lockReason": reason,
            "acousticFlag": acoustic_flag,
            "timestamp": int(time.time() * 1000),
        }
        self._locks[session_id] = payload  # set before any await: concurrent callers lose the race
        incident = {
            "sessionId": session_id,
            "timestamp": None,  # the Firestore logger fills a server timestamp
            "riskScore": risk_score,
            "reason": reason,
            "acousticFlag": acoustic_flag,
            "status": "PAYMENT_LOCKED",
            "enforcement": "DUAL_CHANNEL_ACTIVE",
        }
        # Enforcement first and in parallel with the audit write; a logging failure never delays or blocks it.
        results = await asyncio.gather(
            self._broadcast.broadcast(session_id, payload),
            self._log(incident),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.error("Lockdown side effect failed for %s: %r", session_id, result)
        logger.info("LOCK_SESSION dispatched for %s", session_id)
        return payload

    async def _log(self, incident: dict[str, Any]) -> None:
        try:
            await asyncio.wait_for(self._incidents.log_incident(incident), LOG_TIMEOUT_S)
        except Exception as exc:
            logger.error("Incident log failed: %s", exc)

    async def handle_risk(
        self, session_id: str, risk_score: float, reason: str, acoustic_flag: str | None = None
    ) -> bool:
        """Entry point for the Supervisor Agent. Above the threshold: speak and lock at the same time."""
        if isinstance(risk_score, bool) or not isinstance(risk_score, (int, float)) or math.isnan(risk_score):
            return False
        if risk_score <= RISK_THRESHOLD:
            return False
        jobs = [self.lock_session(session_id, float(risk_score), reason, acoustic_flag)]
        entry = self._live.get(session_id)
        if entry is not None and session_id not in self._spoken and session_id not in self._speaking:
            jobs.append(self._speak(session_id, entry, float(risk_score), reason))
        await asyncio.gather(*jobs, return_exceptions=True)
        return True

    async def _speak(self, session_id: str, entry: tuple[TextTurnSender, str], risk_score: float, reason: str) -> None:
        client, token = entry
        self._speaking.add(session_id)
        self._live.arm(session_id)  # armed before sending so the first audio chunk is not dropped
        try:
            delivered = await inject_barge_in_trigger(client, token, risk_score, reason)
        except Exception as exc:
            logger.error("Barge-in trigger failed: %s", exc)
            delivered = False
        finally:
            self._speaking.discard(session_id)
        if delivered:
            self._spoken.add(session_id)
        else:
            self._live.disarm(session_id)  # a later risk event may try again
