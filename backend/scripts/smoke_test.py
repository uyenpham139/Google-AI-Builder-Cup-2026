import os
import json
from app.agents.coercion.doa_agent import verify_treasury_policy, DoAComplianceAgent

def run_smoke_test():
    print("="*60)
    print("SMOKE TEST 1: DIRECT TOOL CALL (No API Key Required)")
    print("="*60)
    
    # Scenario 1: Critical Policy Breach
    print("\n--- Scenario 1: Critical Violation ---")
    result_fail = verify_treasury_policy(
        operator_id="acc_uyen_01",
        amount_usd=25600000.0,
        beneficiary_account="8829-1029-XXXX"
    )
    print(json.dumps(result_fail, indent=4, ensure_ascii=False))

    # Scenario 2: Whitelisted & Compliant
    print("\n--- Scenario 2: Fully Compliant ---")
    result_pass = verify_treasury_policy(
        operator_id="acc_uyen_01",
        amount_usd=50000.0,
        beneficiary_account="VCB-CORPORATE-PARTNER-01"
    )
    print(json.dumps(result_pass, indent=4, ensure_ascii=False))

    print("\n" + "="*60)
    print("SMOKE TEST 2: AGENT FLOW (Requires GEMINI_API_KEY)")
    print("="*60)
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("SKIP: Please set the GEMINI_API_KEY environment variable to test the Agent Flow.")
        print('Example: $env:GEMINI_API_KEY="AIzaSy..."')
    else:
        print("\n--- Sending Prompt to Gemini ---")
        agent = DoAComplianceAgent(api_key=api_key)
        prompt = "Employee Ngoc Uyen (ID acc_uyen_01) requests to transfer 25600000 USD to account 8829-1029-XXXX."
        print(f"Prompt: '{prompt}'")
        
        try:
            agent_result = agent.process_transaction_request(prompt)
            print("\n--- Agent Result ---")
            print(json.dumps(agent_result, indent=4, ensure_ascii=False))
        except Exception as e:
            print(f"Error calling Gemini API: {e}")

if __name__ == "__main__":
    run_smoke_test()
