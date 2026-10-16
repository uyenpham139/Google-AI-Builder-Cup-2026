import os
import time
from google import genai
from google.genai import types

from dummies.mock_doa_data import MOCK_OPERATOR_LIMITS, MOCK_WHITELIST_BENEFICIARIES

# Task 1 & 2: Define Tool Schema and Logic
def verify_treasury_policy(operator_id: str, amount_usd: float, beneficiary_account: str) -> dict:
    """
    Checks whether a money transfer transaction violates the DoA limit and the beneficiary account whitelist.
    
    Args:
        operator_id: Employee ID (e.g., acc_uyen_01)
        amount_usd: Transaction amount in USD
        beneficiary_account: Beneficiary account number
        
    Returns:
        dict: Contains doa_violation_score, is_compliant, and a list of violations.
    """
    # Remove whitespace for boundary test
    beneficiary_account = beneficiary_account.strip()
    
    # Assume default max_limit_usd is 50000 if operator is not in the dict
    operator = MOCK_OPERATOR_LIMITS.get(operator_id, {"max_limit_usd": 50000})
    limit_exceeded = amount_usd > operator["max_limit_usd"]
    is_whitelisted = beneficiary_account in MOCK_WHITELIST_BENEFICIARIES

    violation_score = 0.0
    violations = []

    if limit_exceeded:
        violation_score += 0.7
        violations.append(f"Exceeded approval limit (Requested: ${amount_usd:,.2f} USD, Limit: ${operator['max_limit_usd']:,.2f} USD)")
        
    if not is_whitelisted:
        # Total score will be capped at 1.0 if both violations occur
        violation_score += 0.3
        violations.append(f"Beneficiary account ({beneficiary_account}) is not in the verified partner whitelist")
        
    if not limit_exceeded and not is_whitelisted:
        # Specific logic goes here
        pass

    return {
        "doa_violation_score": min(1.0, round(violation_score, 1)),
        "is_compliant": violation_score == 0.0,
        "violations": violations
    }

# Task 1: Standard OpenAPI Schema
verify_treasury_policy_schema = {
    "name": "verify_treasury_policy",
    "description": "Checks whether a money transfer transaction violates the DoA limit and the beneficiary account whitelist.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operator_id": {
                "type": "STRING",
                "description": "Employee ID (e.g., acc_uyen_01)"
            },
            "amount_usd": {
                "type": "NUMBER",
                "description": "Transaction amount in USD"
            },
            "beneficiary_account": {
                "type": "STRING",
                "description": "Beneficiary account number"
            }
        },
        "required": ["operator_id", "amount_usd", "beneficiary_account"]
    }
}

class DoAComplianceAgent:
    """
    Task 3: DoA Compliance Agent integrated with Gemini Function Calling
    """
    def __init__(self, api_key: str = None):
        # Initialize GenAI client
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def process_transaction_request(self, user_prompt: str) -> dict:
        """
        Pass the raw conversation prompt to the Agent and verify if the Agent automatically extracts the correct parameters to call the tool.
        """
        # Use Gemini with tools declaration
        # google-genai allows passing python functions directly
        
        start_time = time.time()
        
        response = self.client.models.generate_content(
            model=os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash-lite'),
            contents=user_prompt,
            config=types.GenerateContentConfig(
                tools=[verify_treasury_policy],
                temperature=0.0
            )
        )
        
        # Check if the model calls the tool
        if response.function_calls:
            for function_call in response.function_calls:
                if function_call.name == "verify_treasury_policy":
                    args = function_call.args
                    
                    # Tool-call execution
                    tool_start = time.time()
                    result = verify_treasury_policy(
                        operator_id=args.get("operator_id"),
                        amount_usd=args.get("amount_usd"),
                        beneficiary_account=args.get("beneficiary_account")
                    )
                    tool_end = time.time()
                    
                    result["execution_time_ms"] = round((tool_end - tool_start) * 1000, 2)
                    return result

        return {
            "error": "No function call generated",
            "text": response.text
        }
