"""Manual risk trigger, a stand-in for the Supervisor Agent (Feature 2). Off unless explicitly enabled."""
import hmac
import os
import re

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.services.intervention import runtime

router = APIRouter()

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class RiskEvent(BaseModel):
    sessionId: str
    riskScore: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=200)
    acousticFlag: str | None = Field(default=None, max_length=100)

    @field_validator("sessionId")
    @classmethod
    def _valid_session_id(cls, value: str) -> str:
        if not SESSION_ID_RE.match(value):
            raise ValueError("invalid sessionId")
        return value


@router.post("/internal/risk")
async def post_risk(event: RiskEvent, x_echo_internal_key: str | None = Header(default=None)):
    if os.environ.get("ECHO_ENABLE_RISK_TRIGGER") != "1":
        raise HTTPException(status_code=404)
    expected = os.environ.get("ECHO_INTERNAL_KEY", "")
    if not expected or not hmac.compare_digest((x_echo_internal_key or "").encode(), expected.encode()):
        raise HTTPException(status_code=403)
    triggered = await runtime.lockdown.handle_risk(
        event.sessionId, event.riskScore, event.reason, event.acousticFlag
    )
    return {"triggered": triggered}
