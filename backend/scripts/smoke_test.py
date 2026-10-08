import os
import asyncio
import json
import sys
from dotenv import load_dotenv

# Add app to PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.agents.coercion.agent import CoercionIntentAgent

# Force utf-8 stdout for Windows
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    print("=== SMOKE TEST: COERCION INTENT AGENT (GEMINI ONLY) ===")
    
    # Load environment variables
    load_dotenv()
    
    # Remove GCP vars to prevent SDK from routing to Vertex AI
    os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    os.environ.pop("GOOGLE_CLOUD_LOCATION", None)
    
    if not os.getenv("GEMINI_API_KEY"):
        print("[ERROR] GEMINI_API_KEY environment variable is missing. Please add it to backend/.env")
        return
        
    print("[OK] GEMINI_API_KEY found. Initializing agent...")
    
    try:
        agent = CoercionIntentAgent()
    except Exception as e:
        print(f"Initialization error: {e}")
        return

    test_scenario = "Transfer 5 billion to ABC account immediately. This is a top-secret board matter, do not report this to the Chief Accountant."
    
    print("\n--- TEST SCENARIO ---")
    print(f"Input: \"{test_scenario}\"")
    
    print("\n[Running] Calling Gemini to extract entities & evaluate coercion intent...")
    try:
        result = await agent.evaluate_intent(test_scenario)
        print("[SUCCESS] Coercion Intent Evaluation Result:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"\n[ERROR] during API call: {str(e)}")
        print("Please check your GEMINI_API_KEY or network connection.")

if __name__ == "__main__":
    asyncio.run(main())
