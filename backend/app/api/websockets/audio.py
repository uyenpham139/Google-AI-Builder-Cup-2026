from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import time
import asyncio
from typing import List, Dict, Any
from app.agents.coercion.agent import CoercionIntentAgent

router = APIRouter()

class CallSessionState:
    """Manages rolling conversation window and background evaluations per call"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.transcript_history: List[Dict[str, Any]] = []
        self.highest_risk = 0.0
        self.alert_triggered = False

    def add_transcript(self, text: str, speaker: str = "caller"):
        self.transcript_history.append({
            "timestamp": time.time(),
            "speaker": speaker,
            "text": text
        })
        # Keep last 15 turns in rolling window
        if len(self.transcript_history) > 15:
            self.transcript_history.pop(0)

    def get_sliding_window_text(self) -> str:
        return " ".join([item["text"] for item in self.transcript_history])

@router.websocket("/ws/audio")
@router.websocket("/ws/call")
async def call_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = f"session_{int(time.time()*1000)}"
    print(f"[{session_id}] Client connected to Call Stream WebSocket")

    agent = CoercionIntentAgent()
    state = CallSessionState(session_id)

    async def run_tier2_background(window_text: str, current_turn_text: str):
        """Asynchronously calls Gemini without blocking the WebSocket loop"""
        start_time = time.perf_counter()
        try:
            res = await agent.evaluate_intent(window_text, force_llm=True)
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            score = res.get("coercion_score", 0.0)
            
            if score > state.highest_risk:
                state.highest_risk = score

            is_critical = score >= 0.85
            alert_type = "SECURITY_ALERT" if is_critical else "RISK_UPDATE"

            payload = {
                "type": alert_type,
                "session_id": session_id,
                "tier": "TIER_2_GEMINI",
                "risk_score": score,
                "status": "CRITICAL" if is_critical else "SUSPICIOUS" if score >= 0.6 else "NORMAL",
                "matched_tactics": res.get("matched_tactics", []),
                "entities": res.get("entities", {}),
                "trigger_text": current_turn_text,
                "latency_ms": latency_ms,
                "action": "TRIGGER_BARGE_IN_AND_LOCK" if is_critical else "MONITOR"
            }
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
            print(f"[{session_id}] Pushed Tier-2 Alert to client: Risk={score} in {latency_ms}ms")
        except Exception as e:
            print(f"[{session_id}] Background Tier-2 evaluation error: {e}")

    try:
        while True:
            # Receive either binary audio chunk or JSON transcript
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                # Audio PCM chunk
                data = message["bytes"]
                await websocket.send_text(json.dumps({
                    "type": "AUDIO_ACK",
                    "bytes_received": len(data)
                }))

            elif "text" in message and message["text"]:
                raw_text = message["text"]
                try:
                    payload = json.loads(raw_text)
                except Exception:
                    payload = {"type": "transcript", "text": raw_text}

                msg_type = payload.get("type", "transcript")

                if msg_type == "transcript":
                    turn_text = payload.get("text", "").strip()
                    speaker = payload.get("speaker", "caller")

                    if not turn_text:
                        continue

                    # 1. Update rolling sliding window
                    state.add_transcript(turn_text, speaker)
                    sliding_window = state.get_sliding_window_text()

                    # 2. Fast Tier-1 Guard Scan (< 1ms)
                    start_t1 = time.perf_counter()
                    t1_res = agent.keyword_guard.scan_segment(turn_text)
                    t1_latency = round((time.perf_counter() - start_t1) * 1000, 3)

                    should_deep_analyze = t1_res["should_trigger_llm"]

                    if not should_deep_analyze:
                        # Benign conversation -> Fast Response, 0 token used
                        await websocket.send_text(json.dumps({
                            "type": "STATUS_OK",
                            "session_id": session_id,
                            "tier": "TIER_1_LOCAL",
                            "status": "NORMAL",
                            "risk_score": t1_res["tier1_risk_score"],
                            "llm_skipped": True,
                            "latency_ms": t1_latency,
                            "text": turn_text
                        }, ensure_ascii=False))
                    else:
                        # Suspicious signals detected -> Immediate notification + Non-blocking Tier-2 LLM
                        await websocket.send_text(json.dumps({
                            "type": "TIER1_TRIGGERED",
                            "session_id": session_id,
                            "tier": "TIER_1_LOCAL",
                            "status": "SUSPICIOUS_FORWARDED",
                            "signals": t1_res["detected_signals"],
                            "latency_ms": t1_latency,
                            "notice": "Suspicious financial coercion detected. Forwarding to Gemini Cloud..."
                        }, ensure_ascii=False))

                        # Fire and forget Tier-2 evaluation in background (Non-blocking!)
                        asyncio.create_task(run_tier2_background(sliding_window, turn_text))

                elif msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        print(f"[{session_id}] Client disconnected from Call Stream WebSocket")
