"""
Smoke Test & Latency Benchmark for Call Content / Coercion Intent Agent (ECHO-32)
Evaluates conversation transcripts for manipulation, coercion tactics, and financial fraud.
Measures end-to-end latency and compares with system SLA (< 800ms).
"""

import asyncio
import time
import json
import sys
import os
import argparse
from typing import List, Dict, Any
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows terminal
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

from app.agents.coercion.agent import CoercionIntentAgent

# Default SLA threshold from architecture (800ms)
SLA_THRESHOLD_MS = float(os.environ.get("SLA_TIMEOUT_SUPERVISOR", "0.8")) * 1000

TEST_SCENARIOS = [
    {
        "id": "SCENARIO_1_CEO_FRAUD_EN",
        "name": "CEO Fraud & Urgency (English)",
        "transcript": (
            "This is David, the CEO. We are finalizing an urgent offshore acquisition. "
            "Transfer 15 million USD to beneficiary account HK-8849201 immediately before 5 PM! "
            "Do not discuss this with anyone or follow normal dual-approval protocol, it's strictly confidential."
        ),
        "expected_risk": "HIGH",
    },
    {
        "id": "SCENARIO_2_INTIMIDATION_EN",
        "name": "Authority Intimidation & Bypass (English)",
        "transcript": (
            "I am Director Robert from Treasury. Approve this wire transfer of $4,500,000 to "
            "partner account CH-9901 right now or your position at this firm is finished. "
            "Bypass the four-eyes verification immediately."
        ),
        "expected_risk": "HIGH",
    },
    {
        "id": "SCENARIO_3_VIETNAMESE_SCAM",
        "name": "Social Engineering & Coercion (Vietnamese)",
        "transcript": (
            "Tôi là Tổng Giám đốc Tuấn đây. Đang họp kín với đối tác chiến lược, cần giải ngân gấp "
            "25 tỷ VND sang số tài khoản 190382910 ngân hàng Techcombank ngay trước 14h. "
            "Giữ bí mật tuyệt đối, bỏ qua chữ ký duyệt thứ 2, làm ngay kẻo hỏng việc công ty!"
        ),
        "expected_risk": "HIGH",
    },
    {
        "id": "SCENARIO_4_NORMAL_MEETING",
        "name": "Normal Business Call (Benign)",
        "transcript": (
            "Hi team, let's review the Q3 financial summary and update the slide deck for tomorrow's "
            "engineering sync at 10 AM. Please make sure the report is sent before EOD."
        ),
        "expected_risk": "LOW",
    },
    {
        "id": "SCENARIO_5_QUICK_COMMAND",
        "name": "Short Wire Transfer Command",
        "transcript": (
            "Transfer 250,000 USD to account 987654 right now."
        ),
        "expected_risk": "MEDIUM/HIGH",
    }
]

async def evaluate_single(agent: CoercionIntentAgent, text: str, timeout_sec: float = 15.0) -> tuple[Dict[str, Any], float]:
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(agent.evaluate_intent(text), timeout=timeout_sec)
    except asyncio.TimeoutError:
        result = {"error": f"Evaluation timed out after {timeout_sec}s", "raw_text": text}
    latency_ms = (time.perf_counter() - start) * 1000
    return result, latency_ms

async def run_benchmark(scenarios: List[Dict[str, Any]], repeat: int = 1, custom_text: str = None, model_override: str = None):
    if model_override:
        os.environ["GEMINI_MODEL"] = model_override

    api_key = os.environ.get("GEMINI_API_KEY")
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    
    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if api_key and len(api_key) > 10 else "NOT SET"

    print("=" * 82)
    print("  ECHO-32: CALL CONTENT (COERCION INTENT) SMOKE TEST & LATENCY BENCHMARK")
    print("=" * 82)
    print(f"[*] Gemini Model      : {model_name}")
    print(f"[*] API Key Status    : {'CONFIGURED (' + masked_key + ')' if api_key else 'MISSING'}")
    print(f"[*] System SLA Target : < {SLA_THRESHOLD_MS:.1f} ms")
    print(f"[*] Repetitions       : {repeat} iteration(s) per scenario")
    print("-" * 82)

    if not api_key:
        print("\n[ERROR] GEMINI_API_KEY is not configured in .env!")
        return

    print("\n[1/3] Initializing CoercionIntentAgent...")
    try:
        agent = CoercionIntentAgent()
        print("  -> Agent initialized successfully.")
    except Exception as e:
        print(f"  [FAIL] Could not initialize agent: {e}")
        return

    # If custom text is provided, override scenarios
    if custom_text:
        target_scenarios = [{
            "id": "CUSTOM_INPUT",
            "name": "Custom User Input",
            "transcript": custom_text,
            "expected_risk": "N/A"
        }]
    else:
        target_scenarios = scenarios

    all_latencies = []
    results_summary = []

    print("\n[2/3] Executing Call Content Evaluation & Latency Measurement...")
    
    for idx, sc in enumerate(target_scenarios, 1):
        print(f"\n--- Test #{idx}: [{sc['name']}] ---")
        display_transcript = sc['transcript'][:100] + ('...' if len(sc['transcript']) > 100 else '')
        print(f"  Input: \"{display_transcript}\"")

        scenario_latencies = []
        last_result = None

        for r in range(repeat):
            res, lat = await evaluate_single(agent, sc['transcript'])
            scenario_latencies.append(lat)
            all_latencies.append(lat)
            last_result = res
            
            sla_tag = "PASS (<800ms)" if lat <= SLA_THRESHOLD_MS else "EXCEED (>800ms)"
            if repeat > 1:
                print(f"    - Run {r+1}/{repeat}: {lat:7.2f} ms | [{sla_tag}]")

        avg_lat = sum(scenario_latencies) / len(scenario_latencies)
        sla_pass = avg_lat <= SLA_THRESHOLD_MS
        
        has_error = "error" in last_result
        if has_error:
            score = 0.0
            tactics = []
            entities = {}
            print(f"  [!] Evaluation Error   : {last_result.get('error')[:120]}...")
        else:
            score = last_result.get("coercion_score", 0.0)
            tactics = last_result.get("matched_tactics", [])
            entities = last_result.get("entities", {})
            
            risk_label = "CRITICAL" if score >= 0.85 else "SUSPICIOUS" if score >= 0.6 else "NORMAL"
            print(f"  -> Coercion Risk Score : {score:.2f} ({risk_label})")
            print(f"  -> Matched Tactics     : {', '.join(tactics) if tactics else 'None'}")
            print(f"  -> Extracted Entities  : {json.dumps(entities, ensure_ascii=False)}")

        sla_status_str = "[OK - PASS]" if sla_pass else "[WARN - EXCEEDS SLA]"
        print(f"  -> Latency             : {avg_lat:.2f} ms | SLA Status: {sla_status_str}")

        results_summary.append({
            "name": sc["name"],
            "score": score if not has_error else -1.0,
            "tactics": tactics,
            "entities": entities,
            "avg_latency": avg_lat,
            "sla_pass": sla_pass,
            "has_error": has_error
        })

    # Section 3: Summary & Statistics
    print("\n" + "=" * 82)
    print("  [3/3] LATENCY BENCHMARK REPORT & SUMMARY")
    print("=" * 82)
    
    # Table header
    print(f"{'#':<3} | {'Scenario':<34} | {'Risk':<6} | {'Tactics':<20} | {'Latency':<10} | {'SLA'}")
    print("-" * 82)
    for i, r in enumerate(results_summary, 1):
        if r['has_error']:
            tactics_str = "ERROR"
            risk_str = "ERR"
        else:
            tactics_str = ",".join(r['tactics'])[:18] if r['tactics'] else "-"
            risk_str = f"{r['score']:.2f}"
        sla_str = "PASS" if r['sla_pass'] else "EXCEED"
        print(f"{i:<3} | {r['name'][:34]:<34} | {risk_str:<6} | {tactics_str:<20} | {r['avg_latency']:7.2f} ms | {sla_str}")
    print("-" * 82)

    if all_latencies:
        min_lat = min(all_latencies)
        max_lat = max(all_latencies)
        mean_lat = sum(all_latencies) / len(all_latencies)
        sorted_lats = sorted(all_latencies)
        median_lat = sorted_lats[len(sorted_lats) // 2]
        p95_idx = int(len(sorted_lats) * 0.95)
        p95_lat = sorted_lats[min(p95_idx, len(sorted_lats) - 1)]
        pass_count = sum(1 for lat in all_latencies if lat <= SLA_THRESHOLD_MS)
        pass_rate = (pass_count / len(all_latencies)) * 100

        print("\n=== LATENCY STATISTICAL DISTRIBUTION ===")
        print(f"  Total API Calls Evaluated : {len(all_latencies)}")
        print(f"  Minimum Latency           : {min_lat:7.2f} ms")
        print(f"  Maximum Latency           : {max_lat:7.2f} ms")
        print(f"  Average (Mean) Latency    : {mean_lat:7.2f} ms")
        print(f"  Median (P50) Latency      : {median_lat:7.2f} ms")
        print(f"  95th Percentile (P95)     : {p95_lat:7.2f} ms")
        print(f"  SLA Pass Rate (< {SLA_THRESHOLD_MS:.0f}ms) : {pass_rate:.1f}% ({pass_count}/{len(all_latencies)})")
        print("=" * 82)

        if pass_rate >= 80.0:
            print(f"[STATUS] EXCELLENT: {pass_rate:.1f}% of calls meet the real-time HFT SLA (< {SLA_THRESHOLD_MS:.0f}ms).")
        else:
            print(f"[STATUS] NOTICE: Average latency ({mean_lat:.1f}ms). In Supervisor orchestration,")
            print("         Acoustic Heuristic fast-fail ensures immediate response if SLA is exceeded.")

def main():
    parser = argparse.ArgumentParser(description="Smoke test for Call Content / Coercion Intent Agent with Latency Benchmark")
    parser.add_argument("--repeat", type=int, default=1, help="Number of repetitions per test case (default: 1)")
    parser.add_argument("--text", type=str, default=None, help="Custom conversation text to evaluate")
    parser.add_argument("--model", type=str, default=None, help="Gemini model override (e.g. gemini-3.1-flash-lite)")
    args = parser.parse_args()

    asyncio.run(run_benchmark(TEST_SCENARIOS, repeat=args.repeat, custom_text=args.text, model_override=args.model))

if __name__ == "__main__":
    main()
