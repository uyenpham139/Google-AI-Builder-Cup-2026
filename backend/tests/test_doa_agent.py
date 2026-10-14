import pytest
from app.agents.coercion.doa_agent import verify_treasury_policy

def test_verify_treasury_policy_pass():
    # amount = 50000 (PASS) for operator 'acc_uyen_01' (limit 100000)
    result = verify_treasury_policy(
        operator_id="acc_uyen_01",
        amount_usd=50000.0,
        beneficiary_account="VCB-CORPORATE-PARTNER-01"
    )
    assert result["is_compliant"] is True
    assert result["doa_violation_score"] == 0.0
    assert len(result["violations"]) == 0

def test_verify_treasury_policy_fail_amount_and_account():
    # amount = 25000000 (FAIL), account = unknown (FAIL)
    result = verify_treasury_policy(
        operator_id="acc_uyen_01",
        amount_usd=25600000.0,
        beneficiary_account="8829-1029-XXXX"
    )
    assert result["is_compliant"] is False
    assert result["doa_violation_score"] == 1.0
    assert len(result["violations"]) == 2

def test_verify_treasury_policy_boundary_whitespace():
    # Boundary test: whitelist account has spaces around it
    result = verify_treasury_policy(
        operator_id="acc_uyen_01",
        amount_usd=50000.0,
        beneficiary_account="  VCB-CORPORATE-PARTNER-01  "
    )
    assert result["is_compliant"] is True
    assert result["doa_violation_score"] == 0.0

def test_verify_treasury_policy_limit_only():
    # amount = 100001 (FAIL), account = VCB-CORPORATE-PARTNER-01 (PASS)
    result = verify_treasury_policy(
        operator_id="acc_uyen_01",
        amount_usd=100001.0, # Just 1 USD over limit
        beneficiary_account="VCB-CORPORATE-PARTNER-01"
    )
    assert result["is_compliant"] is False
    assert result["doa_violation_score"] == 0.7
    assert len(result["violations"]) == 1
    assert "Exceeded approval limit" in result["violations"][0]
