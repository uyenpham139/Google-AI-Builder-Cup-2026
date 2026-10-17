import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from app.agents.supervisor.agent import SupervisorAgent

# Mock Agents
class MockAcousticAgent:
    def __init__(self, score):
        self.score = score
    async def evaluate_pcm_artifacts(self, pcm_bytes):
        # Simulate small delay
        await asyncio.sleep(0.01)
        return {"acoustic_score": self.score}

class MockCoercionAgent:
    def __init__(self, score):
        self.score = score
    async def evaluate_intent(self, text):
        await asyncio.sleep(0.01)
        return {"coercion_score": self.score}

class MockDoAAgent:
    def __init__(self, score):
        self.score = score
    def verify_treasury_policy(self, operator_id, amount, beneficiary):
        time.sleep(0.01)
        return {"doa_violation_score": self.score}

@pytest.mark.asyncio
async def test_supervisor_matrix_scenarios():
    """
    Test 5 matrix scenarios.
    Formula: RiskScore = 0.45*A + 0.35*C + 0.20*D
    Threshold: > 0.85 -> CRITICAL (enforce action)
    """
    scenarios = [
        # (A, C, D, ExpectedRisk, ExpectedStatus, ExpectedEnforce)
        # 1. Extreme Critical (Arup Case logic, elevated to 0.95 by fast-fail)
        (0.94, 0.88, 1.0, 0.95, "CRITICAL", True),
        # 2. Warning but safe (<0.85)
        (0.70, 0.80, 0.0, 0.595, "NORMAL", False), # Wait, 0.595 < 0.6 -> NORMAL
        # 3. High Warning (< 0.85)
        (0.85, 0.85, 0.5, 0.78, "WARNING", False), # 0.45*0.85 + 0.35*0.85 + 0.2*0.5 = 0.3825 + 0.2975 + 0.1 = 0.78 -> WARNING
        # 4. Safe / Baseline
        (0.10, 0.15, 0.0, 0.098, "NORMAL", False),
        # 5. Just over threshold (elevated to 0.95 by fast-fail)
        (0.90, 0.95, 0.8, 0.95, "CRITICAL", True)
    ]

    for a_score, c_score, d_score, expected_risk, expected_status, expected_enforce in scenarios:
        barge_in_handler = AsyncMock()
        broadcast_handler = AsyncMock()

        supervisor = SupervisorAgent(
            acoustic_agent=MockAcousticAgent(a_score),
            coercion_agent=MockCoercionAgent(c_score),
            doa_agent=MockDoAAgent(d_score),
            barge_in_handler=barge_in_handler,
            broadcast_handler=broadcast_handler
        )

        result = await supervisor.evaluate_meeting_step(
            session_id="test_session",
            pcm_bytes=b"dummy",
            transcript_text="dummy text",
            erp_context={"operator_id": "acc_01", "amount": 100, "beneficiary": "acc_02"}
        )

        assert result["risk_score"] == expected_risk
        assert result["status"] == expected_status

        if expected_enforce:
            barge_in_handler.assert_awaited_once()
            broadcast_handler.assert_awaited_once()
            assert "test_session" in supervisor.enforced_sessions
        else:
            barge_in_handler.assert_not_awaited()
            broadcast_handler.assert_not_awaited()

@pytest.mark.asyncio
async def test_supervisor_state_latching():
    """
    Test State Latching & Debounce (Ensure it doesn't trigger multiple times for the same session)
    """
    barge_in_handler = AsyncMock()
    broadcast_handler = AsyncMock()

    supervisor = SupervisorAgent(
        acoustic_agent=MockAcousticAgent(0.94),
        coercion_agent=MockCoercionAgent(0.88),
        doa_agent=MockDoAAgent(1.0),
        barge_in_handler=barge_in_handler,
        broadcast_handler=broadcast_handler
    )

    # First call - should trigger
    await supervisor.evaluate_meeting_step("session_arup", b"", "", {})
    
    # Check trigger counts
    assert barge_in_handler.call_count == 1
    assert broadcast_handler.call_count == 1

    # Second call for the SAME session - should NOT trigger again
    await supervisor.evaluate_meeting_step("session_arup", b"", "", {})
    
    # Counts should still be 1
    assert barge_in_handler.call_count == 1
    assert broadcast_handler.call_count == 1

    # Call for a DIFFERENT session - should trigger
    await supervisor.evaluate_meeting_step("session_other", b"", "", {})
    
    # Counts should increment to 2
    assert barge_in_handler.call_count == 2
    assert broadcast_handler.call_count == 2

@pytest.mark.asyncio
async def test_end_to_end_arup_simulation():
    """
    Simulates the Arup HK$200M attack scenario.
    """
    barge_in_handler = AsyncMock()
    broadcast_handler = AsyncMock()

    # In Arup attack: Highly synthetic voice, high coercion (CFO ordering), highly unusual transaction (DoA breach)
    supervisor = SupervisorAgent(
        acoustic_agent=MockAcousticAgent(0.99), # Deepfake CFO
        coercion_agent=MockCoercionAgent(0.95), # "Transfer HK$200M now, strictly confidential!"
        doa_agent=MockDoAAgent(1.0),            # Massive limit breach, unverified accounts
        barge_in_handler=barge_in_handler,
        broadcast_handler=broadcast_handler
    )

    erp_context = {
        "operator_id": "clerk_01",
        "amount": 25000000,
        "beneficiary": "offshore_unknown_acc"
    }

    start_time = time.perf_counter()
    result = await supervisor.evaluate_meeting_step(
        session_id="arup_incident",
        pcm_bytes=b"fake_cfo_voice_data",
        transcript_text="This is a highly confidential acquisition. Transfer 25 million USD immediately.",
        erp_context=erp_context
    )
    end_time = time.perf_counter()
    
    # The evaluation itself should take roughly max of 3 agents (since they run in parallel)
    # Our mocks sleep for 10ms, so total time should be ~10-20ms. Total decision latency NFR < 800ms.
    assert (end_time - start_time) < 0.8

    assert result["status"] == "CRITICAL"
    assert result["risk_score"] > 0.85
    
    # Verify triggers were fired with correct session
    barge_in_handler.assert_awaited_once()
    broadcast_handler.assert_awaited_once()
    
    # Check that reason contains breakdown
    call_args = barge_in_handler.call_args[0]
    assert call_args[0] == "arup_incident"
    assert call_args[1] == result["risk_score"]
    assert "Voice Clone" in call_args[2]
