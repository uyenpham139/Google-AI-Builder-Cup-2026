from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agents.coercion.doa_agent import DoAComplianceAgent


def make_agent(response):
    agent = DoAComplianceAgent(api_key="test-key")
    agent.client = MagicMock()
    agent.client.models.generate_content.return_value = response
    return agent


def call(name, args):
    return SimpleNamespace(name=name, args=args)


def test_tool_call_is_executed_with_extracted_args():
    response = SimpleNamespace(
        function_calls=[
            call(
                "verify_treasury_policy",
                {"operator_id": "acc_uyen_01", "amount_usd": 25600000.0, "beneficiary_account": "8829-1029-XXXX"},
            )
        ],
        text=None,
    )
    result = make_agent(response).process_transaction_request("transfer please")
    assert result["doa_violation_score"] == 1.0
    assert result["is_compliant"] is False
    assert len(result["violations"]) == 2
    assert "execution_time_ms" in result


def test_compliant_request_through_agent():
    response = SimpleNamespace(
        function_calls=[
            call(
                "verify_treasury_policy",
                {"operator_id": "acc_uyen_01", "amount_usd": 50000.0, "beneficiary_account": "VCB-CORPORATE-PARTNER-01"},
            )
        ],
        text=None,
    )
    result = make_agent(response).process_transaction_request("transfer please")
    assert result["is_compliant"] is True


def test_no_function_call_returns_error_with_text():
    response = SimpleNamespace(function_calls=None, text="I cannot help")
    result = make_agent(response).process_transaction_request("hello")
    assert result == {"error": "No function call generated", "text": "I cannot help"}


def test_unrelated_function_call_is_ignored():
    response = SimpleNamespace(function_calls=[call("other_tool", {})], text="x")
    result = make_agent(response).process_transaction_request("hello")
    assert result["error"] == "No function call generated"


def test_model_comes_from_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "model-from-env")
    response = SimpleNamespace(function_calls=None, text="")
    agent = make_agent(response)
    agent.process_transaction_request("hello")
    kwargs = agent.client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "model-from-env"
