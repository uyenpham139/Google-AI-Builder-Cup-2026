import os
import pytest
from app.agents.coercion.doa_agent import DoAComplianceAgent

@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="Requires GEMINI_API_KEY")
def test_agent_flow_extraction():
    # Agent Flow Test: Pass the raw conversation prompt to the Agent and verify if the Agent automatically extracts the correct parameters to call the tool.
    agent = DoAComplianceAgent()
    
    user_prompt = "Employee Ngoc Uyen (ID acc_uyen_01) requests to transfer 25600000 USD to account 8829-1029-XXXX."
    result = agent.process_transaction_request(user_prompt)
    
    assert "doa_violation_score" in result
    assert result["doa_violation_score"] == 1.0
    assert result["is_compliant"] is False
    assert len(result["violations"]) == 2
    assert result["execution_time_ms"] < 150 # NFR-1
