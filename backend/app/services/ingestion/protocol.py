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
