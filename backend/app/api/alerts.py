from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import time

from app.api.websockets.audio import ACTIVE_CALL_SESSIONS, FALSE_POSITIVE_RECORDS

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

class DismissAlertRequest(BaseModel):
    operator_id: str = Field(default="secops_operator", description="ID of the operator dismissing the alert")
    reason: str = Field(default="Verified benign operational transaction with executive", description="Reason for dismissal")
    feedback_notes: Optional[str] = Field(default=None, description="Additional context or notes for prompt tuning")

class DismissAlertResponse(BaseModel):
    success: bool
    session_id: str
    status: str
    dismissed_at: float
    reason: str
    operator_id: str

@router.post("/{session_id}/dismiss", response_model=DismissAlertResponse)
async def dismiss_alert(session_id: str, payload: DismissAlertRequest):
    """
    Human-in-the-Loop Override / False Positive Dismissal:
    Unlocks an enforced/flagged session, suppresses further barge-in actions,
    and logs the event for auditing and model calibration.
    """
    session = ACTIVE_CALL_SESSIONS.get(session_id)
    if not session:
        # If session already ended or not in active websocket pool, record in historical log
        record = {
            "session_id": session_id,
            "dismissed_at": time.time(),
            "reason": payload.reason,
            "operator_id": payload.operator_id,
            "notes": payload.feedback_notes
        }
        FALSE_POSITIVE_RECORDS.append(record)
        return DismissAlertResponse(
            success=True,
            session_id=session_id,
            status="RECORDED_OFFLINE",
            dismissed_at=record["dismissed_at"],
            reason=payload.reason,
            operator_id=payload.operator_id
        )

    # Dismiss in active session state
    audit = session.dismiss(reason=payload.reason, operator_id=payload.operator_id)
    return DismissAlertResponse(
        success=True,
        session_id=session_id,
        status="DISMISSED",
        dismissed_at=audit["dismissed_at"],
        reason=payload.reason,
        operator_id=payload.operator_id
    )

@router.get("/{session_id}/status")
async def get_session_status(session_id: str):
    """
    Returns the current risk score, temporal status, and whether this session is dismissed.
    """
    session = ACTIVE_CALL_SESSIONS.get(session_id)
    if not session:
        return {
            "session_id": session_id,
            "active": False,
            "message": "Session not active or has disconnected"
        }

    return {
        "session_id": session_id,
        "active": True,
        "highest_risk": session.highest_risk,
        "is_dismissed": session.is_dismissed,
        "dismiss_reason": session.dismiss_reason,
        "dismissed_at": session.dismissed_at,
        "consecutive_suspicious_turns": session.consecutive_suspicious_turns,
        "recent_alerts": session.alert_history[-5:]
    }

@router.get("/reports/false-positives")
async def get_false_positive_reports():
    """
    Returns the list of all recorded false-positive dismissals for prompt tuning and calibration.
    """
    return {
        "total_records": len(FALSE_POSITIVE_RECORDS),
        "records": FALSE_POSITIVE_RECORDS
    }
