import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.agents.supervisor.agent import SupervisorAgent
from app.api.websockets.audio import CallSessionState, ACTIVE_CALL_SESSIONS

# Mock Agents for Testing
class MockAgent:
    def __init__(self, score: float):
        self.score = score

    async def evaluate_pcm_artifacts(self, pcm_bytes):
        await asyncio.sleep(0.01)
        return {"acoustic_score": self.score}

    async def evaluate_intent(self, text):
        await asyncio.sleep(0.01)
        return {"coercion_score": self.score}

    def verify_treasury_policy(self, operator_id, amount, beneficiary):
        return {"doa_violation_score": self.score}

@pytest.mark.asyncio
async def test_supervisor_isolated_coercion_false_positive_attenuation():
    """
    Test that an isolated Coercion score spike (e.g., legitimate urgency for whitelisted vendor)
    with clean acoustic and compliant DoA does NOT trigger CRITICAL lockdown.
    """
    barge_in_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    # Coercion is high (0.92), but Acoustic is clean (0.10) and DoA is whitelisted compliant (0.0)
    supervisor = SupervisorAgent(
        acoustic_agent=MockAgent(0.10),
        coercion_agent=MockAgent(0.92),
        doa_agent=MockAgent(0.0),
        barge_in_handler=barge_in_mock,
        broadcast_handler=broadcast_mock
    )

    result = await supervisor.evaluate_meeting_step(
        session_id="session_legit_urgent_01",
        pcm_bytes=b"dummy",
        transcript_text="Please transfer urgently before 5pm cut-off to our verified supplier",
        erp_context={"operator_id": "acc_01", "amount": 1000, "beneficiary": "whitelisted_vendor"}
    )

    # Verify mitigation was applied
    assert result["false_positive_mitigation"]["applied"] is True
    assert "Isolated urgency detected" in result["false_positive_mitigation"]["reason"]
    # Risk must be capped at WARNING (<= 0.75), not elevated to 0.95
    assert result["risk_score"] <= 0.75
    assert result["status"] == "WARNING"
    # Barge-in and ERP Lock MUST NOT be triggered
    barge_in_mock.assert_not_awaited()
    broadcast_mock.assert_not_awaited()
    assert "session_legit_urgent_01" not in supervisor.enforced_sessions

@pytest.mark.asyncio
async def test_supervisor_isolated_acoustic_codec_noise_mitigation():
    """
    Test that an isolated Acoustic spike (e.g. VoIP codec distortion/mic crackle)
    without any coercion or DoA violation does NOT lock the meeting.
    """
    barge_in_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    # Acoustic is high (0.95), but Coercion is clean (0.10) and DoA is clean (0.0)
    supervisor = SupervisorAgent(
        acoustic_agent=MockAgent(0.95),
        coercion_agent=MockAgent(0.10),
        doa_agent=MockAgent(0.0),
        barge_in_handler=barge_in_mock,
        broadcast_handler=broadcast_mock
    )

    result = await supervisor.evaluate_meeting_step(
        session_id="session_noisy_mic_02",
        pcm_bytes=b"dummy",
        transcript_text="Good morning team, how are things going today?",
        erp_context={"operator_id": "acc_01", "amount": 0, "beneficiary": "none"}
    )

    assert result["false_positive_mitigation"]["applied"] is True
    assert "Isolated acoustic anomaly" in result["false_positive_mitigation"]["reason"]
    assert result["risk_score"] <= 0.70
    assert result["status"] == "WARNING"
    barge_in_mock.assert_not_awaited()
    broadcast_mock.assert_not_awaited()

@pytest.mark.asyncio
async def test_supervisor_genuine_multi_factor_attack_still_enforces():
    """
    Verify that multi-factor attacks (Deepfake + Coercion + DoA breach) still properly enforce lock.
    """
    barge_in_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    supervisor = SupervisorAgent(
        acoustic_agent=MockAgent(0.95),
        coercion_agent=MockAgent(0.92),
        doa_agent=MockAgent(1.0),
        barge_in_handler=barge_in_mock,
        broadcast_handler=broadcast_mock
    )

    result = await supervisor.evaluate_meeting_step(
        session_id="session_real_attack_03",
        pcm_bytes=b"dummy",
        transcript_text="Transfer 25M USD immediately, tell no one, bypass controls!",
        erp_context={"operator_id": "acc_01", "amount": 25000000, "beneficiary": "unknown_offshore"}
    )

    assert result["false_positive_mitigation"]["applied"] is False
    assert result["risk_score"] >= 0.95
    assert result["status"] == "CRITICAL"
    barge_in_mock.assert_awaited_once()
    broadcast_mock.assert_awaited_once()
    assert "session_real_attack_03" in supervisor.enforced_sessions

@pytest.mark.asyncio
async def test_supervisor_human_dismissal_override():
    """
    Verify that an operator can dismiss an enforced session (False Positive),
    unlocking it and preventing re-lock.
    """
    barge_in_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    supervisor = SupervisorAgent(
        acoustic_agent=MockAgent(0.95),
        coercion_agent=MockAgent(0.95),
        doa_agent=MockAgent(1.0),
        barge_in_handler=barge_in_mock,
        broadcast_handler=broadcast_mock
    )

    session_id = "session_dismiss_04"
    # Step 1: Trigger critical lock
    await supervisor.evaluate_meeting_step(session_id, b"dummy", "dummy text", {})
    assert session_id in supervisor.enforced_sessions

    # Step 2: Operator confirms false positive and dismisses
    dismiss_res = supervisor.dismiss_session(
        session_id=session_id,
        reason="CEO called through internal phone to verify legitimacy",
        operator_id="secops_alice"
    )
    assert dismiss_res["success"] is True
    assert session_id not in supervisor.enforced_sessions
    assert session_id in supervisor.dismissed_sessions

    # Step 3: Next evaluation step acknowledges dismissal and suppresses re-lock
    result_step2 = await supervisor.evaluate_meeting_step(session_id, b"dummy", "dummy text", {})
    assert result_step2["status"] == "OVERRIDDEN_DISMISSED"
    assert result_step2["false_positive_mitigation"]["is_previously_dismissed"] is True

def test_rest_api_dismiss_and_feedback():
    """
    Test REST API endpoints for dismissing alerts and auditing false positives.
    """
    client = TestClient(app)

    # 1. Register a test session
    session_id = "test_rest_session_01"
    session_state = CallSessionState(session_id)
    ACTIVE_CALL_SESSIONS[session_id] = session_state

    # 2. Call dismiss endpoint
    res = client.post(f"/api/alerts/{session_id}/dismiss", json={
        "operator_id": "operator_bob",
        "reason": "Confirmed legitimate business urgency with financial director",
        "feedback_notes": "Prompt misjudged end-of-month bank cut-off as coercion"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] == "DISMISSED"
    assert session_state.is_dismissed is True

    # 3. Check status endpoint
    status_res = client.get(f"/api/alerts/{session_id}/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["is_dismissed"] is True
    assert status_data["dismiss_reason"] == "Confirmed legitimate business urgency with financial director"

    # 4. Check false positive audit report
    report_res = client.get("/api/alerts/reports/false-positives")
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["total_records"] >= 1
