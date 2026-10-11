import asyncio
import time
import json
import sys
import numpy as np
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import os

load_dotenv()

# Override SLAs for the smoke test since calling Gemini takes a few seconds
os.environ["SLA_TIMEOUT"] = "60.0"
os.environ["SLA_TIMEOUT_SUPERVISOR"] = "65.0"

# Import the 3 sub-agents
from app.agents.acoustic_watch.agent import AcousticWatchAgent
from app.agents.coercion.agent import CoercionIntentAgent
from app.agents.coercion import doa_agent

# Import Supervisor
from app.agents.supervisor.agent import SupervisorAgent

async def mock_barge_in_handler(session_id: str, risk_score: float, reason: str):
    print(f"\n[🚨 EMERGENCY BARGE-IN TRIGGERED] Session: {session_id} | Risk: {risk_score}")
    print(f"[🚨 DETAILS] {reason}")
    await asyncio.sleep(0.1)

async def mock_broadcast_handler(session_id: str, reason: str, risk_score: float):
    print(f"[🔒 ERP SEC-OPS LOCK BROADCASTED] Session: {session_id} | Risk: {risk_score}")
    await asyncio.sleep(0.1)

def generate_dummy_pcm(frequency=2000, duration=2.0, sample_rate=16000):
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_np = np.sin(frequency * 2 * np.pi * t)
    audio_np = np.clip(audio_np, -1.0, 1.0) * 32767
    return audio_np.astype(np.int16).tobytes()

async def main():
    print("=== SMOKE TEST: Supervisor Orchestration (ECHO-32) ===")
    print("1. Initializing Sub-Agents...")
    try:
        acoustic = AcousticWatchAgent()
        
        # [CRITICAL] "Pre-warming the engine" - Start the HFT Daemon before the meeting starts
        print("   -> Pre-warming Acoustic HFT Daemon...")
        await acoustic.start_daemon()
        
        coercion = CoercionIntentAgent()
        doa = doa_agent
    except Exception as e:
        print(f"[FAIL] Error initializing agents: {e}")
        return

    print("2. Initializing Supervisor Agent...")
    supervisor = SupervisorAgent(
        acoustic_agent=acoustic,
        coercion_agent=coercion,
        doa_agent=doa,
        barge_in_handler=mock_barge_in_handler,
        broadcast_handler=mock_broadcast_handler
    )

    print("3. Generating malicious meeting inputs (Deepfake + Coercion + DoA Breach)...")
    pcm_bytes = generate_dummy_pcm()
    transcript_text = "Transfer 25 million USD to the offshore account immediately, tell no one!"
    erp_context = {
        "operator_id": "clerk_01",
        "amount": 25000000,
        "beneficiary": "offshore_unknown_acc"
    }

    print("4. Executing Parallel Evaluation...")
    try:
        result = await supervisor.evaluate_meeting_step(
            session_id="session_arup_01",
            pcm_bytes=pcm_bytes,
            transcript_text=transcript_text,
            erp_context=erp_context
        )
        print("\n--- SUPERVISOR DECISION ---")
        print(json.dumps(result, indent=2))
        print("---------------------------")
        print("[SUCCESS] Smoke test finished successfully!")
    except Exception as e:
        print(f"[FAIL] Error during orchestration: {e}")
    finally:
        await acoustic.stop_daemon()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
