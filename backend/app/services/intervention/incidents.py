"""Audit trail for lockdown events (ECHO-25). Cloud Firestore sits behind a small interface."""
import logging
import os
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)

COLLECTION = "incident_logs"


class IncidentLogger(Protocol):
    async def log_incident(self, incident: dict[str, Any]) -> None: ...


class InMemoryIncidentLogger:
    """Used in tests and when no Google Cloud project is configured."""

    def __init__(self):
        self.incidents: list[dict[str, Any]] = []

    async def log_incident(self, incident: dict[str, Any]) -> None:
        self.incidents.append({**incident, "timestamp": incident.get("timestamp") or int(time.time() * 1000)})


class FirestoreIncidentLogger:
    def __init__(self, project: str | None = None, client: Any = None):
        if client is None:
            from google.cloud import firestore  # imported lazily: only needed on Cloud Run

            client = firestore.AsyncClient(project=project)
        self._db = client

    async def log_incident(self, incident: dict[str, Any]) -> None:
        document = dict(incident)
        if document.get("timestamp") is None:
            from google.cloud import firestore

            document["timestamp"] = firestore.SERVER_TIMESTAMP
        await self._db.collection(COLLECTION).document(document["sessionId"]).set(document)


def build_incident_logger() -> IncidentLogger:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        logger.warning("GOOGLE_CLOUD_PROJECT is not set: incident logs stay in memory only")
        return InMemoryIncidentLogger()
    try:
        return FirestoreIncidentLogger(project=project)
    except Exception as exc:  # missing credentials must not stop the backend from booting
        logger.error("Firestore unavailable (%s): incident logs stay in memory only", exc)
        return InMemoryIncidentLogger()
