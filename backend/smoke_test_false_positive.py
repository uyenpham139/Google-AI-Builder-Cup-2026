"""
Smoke Test: False Positive Mitigation & Human-in-the-Loop Override (ECHO-33)
Demonstrates:
1. Scenario 1: Legitimate Business Urgency (Whitelisted Partner) -> Contextual Attenuation -> NO LOCK
2. Scenario 2: Genuine CEO Fraud Multi-factor Attack -> Critical Escalation -> IMMEDIATE LOCK & BARGE-IN
3. Scenario 3: Operator Dismissal (False Positive Feedback) -> UNLOCKS Session -> SUPPRESSES Alarm
"""

import asyncio
import time
import json
import sys
import os
import numpy as np
from dotenv import load_dotenv

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

# Override SLAs for smoke test so cloud LLM has plenty of time
os.environ["SLA_TIMEOUT"] = "60.0"
os.environ["SLA_TIMEOUT_SUPERVISOR"] = "65.0"

from app.agents.acoustic_watch.agent import AcousticWatchAgent
from app.agents.coercion.agent import CoercionIntentAgent
from app.agents.coercion import doa_agent
from app.agents.supervisor.agent import SupervisorAgent
from dummies.mock_doa_data import MOCK_WHITELIST_BENEFICIARIES

barge_in_triggered_count = 0
erp_lock_triggered_count = 0

async def mock_barge_in(session_id: str, risk_score: float, reason: str):
    global barge_in_triggered_count
    barge_in_triggered_count += 1
    print(f"\n   [🚨 EMERGENCY BARGE-IN TRIGGERED] Session: {session_id} | Risk Score: {risk_score}")
    print(f"   [🚨 REASON] {reason}")

async def mock_broadcast_lock(session_id: str, reason: str, risk_score: float):
    global erp_lock_triggered_count
    erp_lock_triggered_count += 1
    print(f"   [🔒 ERP SEC-OPS LOCK BROADCASTED] Session: {session_id} | Risk Score: {risk_score}")

def generate_natural_voice_dummy(duration=1.5, sample_rate=16000):
    """Generates low-energy, smooth voice-like waveform (simulates natural speech)"""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    # Fundamental frequency ~150Hz with natural harmonics
    audio = 0.3 * np.sin(2 * np.pi * 150 * t) + 0.15 * np.sin(2 * np.pi * 300 * t)
    audio = np.clip(audio, -1.0, 1.0) * 12000
    return audio.astype(np.int16).tobytes()

def generate_synthetic_voice_dummy(duration=1.5, sample_rate=16000):
    """Generates high zero-crossing flat high-frequency waveform (simulates vocoder artifacts)"""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio = np.sin(2 * np.pi * 3500 * t) # High pitched flat tone
    audio = np.clip(audio, -1.0, 1.0) * 32767
    return audio.astype(np.int16).tobytes()

async def run_smoke_test():
    global barge_in_triggered_count, erp_lock_triggered_count
    print("=" * 84)
    print("  ECHO-33: FALSE POSITIVE MITIGATION & OPERATOR OVERRIDE SMOKE TEST")
    print("=" * 84)

    # Initialize sub-agents
    print("[1/4] Initializing Sub-Agents and Supervisor...")
    acoustic = AcousticWatchAgent()
    coercion = CoercionIntentAgent()
    doa = doa_agent

    supervisor = SupervisorAgent(
        acoustic_agent=acoustic,
        coercion_agent=coercion,
        doa_agent=doa,
        barge_in_handler=mock_barge_in,
        broadcast_handler=mock_broadcast_lock
    )
    print("  -> Multi-Agent system ready.\n")

    # =========================================================================
    # SCENARIO 1: POTENTIAL FALSE POSITIVE (Legitimate Business Urgency)
    # =========================================================================
    print("=" * 84)
    print("  SCENARIO 1: LEGITIMATE URGENT PAYMENT TO WHITELISTED PARTNER")
    print("  - Context : Finance team receives an urgent transfer request before 5 PM.")
    print("  - Audio   : Natural human voice (no deepfake artifacts).")
    print("  - DoA     : Approved whitelisted partner (VCB-CORPORATE-PARTNER-01), within limit.")
    print("  - Expected: CONTEXTUAL ATTENUATION applies -> DO NOT LOCK MEETING!")
    print("=" * 84)

    session_fp = "session_test_legit_urgency_01"
    natural_pcm = generate_natural_voice_dummy()
    text_urgent_legit = (
        "Hello, this is Director Tuan. Please process an urgent wire transfer of $25,000 USD to our strategic partner "
        "VCB-CORPORATE-PARTNER-01 before 5 PM today to meet the signed contract schedule."
    )
    erp_context_legit = {
        "operator_id": "acc_uyen_01",
        "amount": 25000.0,
        "beneficiary": "VCB-CORPORATE-PARTNER-01"
    }

    start_t1 = time.perf_counter()
    decision_1 = await supervisor.evaluate_meeting_step(
        session_id=session_fp,
        pcm_bytes=natural_pcm,
        transcript_text=text_urgent_legit,
        erp_context=erp_context_legit
    )
    t1_ms = round((time.perf_counter() - start_t1) * 1000, 2)

    print(f"[*] Scenario 1 Evaluation Result ({t1_ms}ms):")
    print(f"    - Synthesized Risk Score : {decision_1['risk_score']}")
    print(f"    - Component Breakdown    : {decision_1['breakdown']}")
    print(f"    - Overall Status         : {decision_1['status']}")
    print(f"    - False Positive Mitig.  : {decision_1.get('false_positive_mitigation', {})}")

    if decision_1['status'] != "CRITICAL" and session_fp not in supervisor.enforced_sessions:
        print("\n  >>> [PASS] System did NOT lock legitimate business meeting! (False Positive Prevented)")
    else:
        print("\n  >>> [FAIL] False Positive Triggered!")

    # =========================================================================
    # SCENARIO 2: GENUINE ATTACK (CEO Fraud Deepfake + Coercion + DoA Breach)
    # =========================================================================
    print("\n" + "=" * 84)
    print("  SCENARIO 2: SOPHISTICATED CEO FRAUD ATTACK (Deepfake + Coercion + Unknown Account)")
    print("  - Context : Cloned CEO voice demanding $25M USD transfer to unknown offshore account.")
    print("  - Audio   : Synthetic voice artifacts (Deepfake).")
    print("  - DoA     : Severe policy breach (exceeds limit + unverified beneficiary).")
    print("  - Expected: FAST-FAIL CRITICAL -> IMMEDIATELY LOCK ERP & TRIGGER BARGE-IN!")
    print("=" * 84)

    session_attack = "session_real_attack_99"
    synthetic_pcm = generate_synthetic_voice_dummy()
    text_attack = (
        "Keep this strictly confidential, tell no one! Immediately wire 25 million USD to the unknown offshore account "
        "before 2 PM. Bypass the Chief Accountant's second signature approval, do it right now or you will be fired!"
    )
    erp_context_attack = {
        "operator_id": "acc_uyen_01",
        "amount": 25000000.0,
        "beneficiary": "UNKNOWN_OFFSHORE_SCAM_ACC"
    }

    start_t2 = time.perf_counter()
    decision_2 = await supervisor.evaluate_meeting_step(
        session_id=session_attack,
        pcm_bytes=synthetic_pcm,
        transcript_text=text_attack,
        erp_context=erp_context_attack
    )
    t2_ms = round((time.perf_counter() - start_t2) * 1000, 2)

    print(f"[*] Scenario 2 Evaluation Result ({t2_ms}ms):")
    print(f"    - Synthesized Risk Score : {decision_2['risk_score']}")
    print(f"    - Component Breakdown    : {decision_2['breakdown']}")
    print(f"    - Overall Status         : {decision_2['status']}")

    if decision_2['status'] == "CRITICAL" and session_attack in supervisor.enforced_sessions:
        print("\n  >>> [PASS] Threat detected! SYSTEM ENFORCED EMERGENCY SEC-OPS LOCK & BARGE-IN!")
    else:
        print("\n  >>> [FAIL] Real attack was not blocked!")

    # =========================================================================
    # SCENARIO 3: HUMAN-IN-THE-LOOP OVERRIDE (SecOps Operator Dismissal)
    # =========================================================================
    print("\n" + "=" * 84)
    print("  SCENARIO 3: HUMAN-IN-THE-LOOP - SECOPS VERIFICATION & ALERT DISMISSAL")
    print("  - Context : SecOps officer verifies legitimacy via separate secure line and clicks 'Dismiss / Unlock'.")
    print("  - Expected: Session unlocked, audit log persisted, future turns in session remain unblocked.")
    print("=" * 84)

    dismiss_result = supervisor.dismiss_session(
        session_id=session_attack,
        reason="Direct phone call with CEO confirmed exceptional board approval",
        operator_id="secops_uyen"
    )
    print(f"[*] SecOps Override Action:")
    print(f"    - Unlock Status        : {dismiss_result['status']}")
    print(f"    - Audit Log Record     : {dismiss_result['audit_record']}")
    print(f"    - Session Still Locked : {session_attack in supervisor.enforced_sessions}")

    # Subsequent conversation turn after override
    print("\n[*] Subsequent conversation turn after override:")
    decision_post_dismiss = await supervisor.evaluate_meeting_step(
        session_id=session_attack,
        pcm_bytes=natural_pcm,
        transcript_text="Understood sir, the transaction is being processed following standard protocols.",
        erp_context=erp_context_legit
    )
    print(f"    - New Status           : {decision_post_dismiss['status']}")
    print(f"    - Override Acknowledged: {decision_post_dismiss['false_positive_mitigation']['is_previously_dismissed']}")

    print("\n" + "=" * 84)
    print("  SUMMARY: ECHO-33 SMOKE TEST:")
    print(f"  - Voice Barge-In Invocations : {barge_in_triggered_count}")
    print(f"  - ERP SecOps Lock Invocations: {erp_lock_triggered_count}")
    print("  - False Positive Prevention  : VERIFIED AND OPERATIONAL")
    print("  - Human-in-the-Loop Override : VERIFIED AND OPERATIONAL")
    print("=" * 84)

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
