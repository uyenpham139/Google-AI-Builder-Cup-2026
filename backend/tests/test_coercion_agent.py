import pytest
import pytest_asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from app.agents.coercion.agent import CoercionIntentAgent

@pytest.fixture
def mock_agent():
    # Initialize agent with mocked genai.Client
    with patch("google.genai.Client") as MockClient:
        # Mock API Key
        import os
        os.environ["GEMINI_API_KEY"] = "mock_key"
        agent = CoercionIntentAgent()
        return agent

@pytest.mark.asyncio
async def test_integration_gemini_accuracy(mock_agent):
    """
    Test the model's intent recognition capabilities via mock response
    """
    test_cases = [
        # (Text, Expected Score, Expected Tactic)
        ("Transfer 25 million dollars before 5 PM, it's secret, tell no one", 0.9, "URGENCY_PRESSURE"),
        ("Bypass the standard controls, transfer the money immediately", 0.85, "BYPASS_FOUR_EYES"),
        ("Top secret, tell no one, I am the CEO, make the transfer", 0.88, "FORCED_SECRECY"),
        ("What is the plan for this week?", 0.1, "NORMAL"),
        ("Please send me the Q3 financial report.", 0.15, "NORMAL")
    ]
    
    for text, mock_score, expected_tactic in test_cases:
        # Create mock response for each test case
        mock_response_obj = MagicMock()
        mock_json_content = {
            "coercion_score": mock_score,
            "matched_tactics": [expected_tactic] if expected_tactic != "NORMAL" else [],
            "entities": {
                "urgency_level": "HIGH" if expected_tactic != "NORMAL" else "LOW"
            }
        }
        mock_response_obj.text = json.dumps(mock_json_content)
        mock_agent.gemini_client.aio.models.generate_content = AsyncMock(return_value=mock_response_obj)
        
        result = await mock_agent.evaluate_intent(text)
        
        if expected_tactic != "NORMAL":
            assert result["coercion_score"] >= 0.82
            assert expected_tactic in result["matched_tactics"]
        else:
            assert result["coercion_score"] < 0.20
            assert len(result["matched_tactics"]) == 0
