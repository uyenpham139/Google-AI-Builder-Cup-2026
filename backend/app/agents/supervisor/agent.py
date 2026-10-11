import asyncio
import time
import inspect
from typing import Callable

class SupervisorAgent:
    def __init__(self, acoustic_agent, coercion_agent, doa_agent, barge_in_handler: Callable, broadcast_handler: Callable):
        self.acoustic_agent = acoustic_agent
        self.coercion_agent = coercion_agent
        self.doa_agent = doa_agent
        self.barge_in_handler = barge_in_handler
        self.broadcast_handler = broadcast_handler
        # State Latching & Debounce per session
        self.enforced_sessions = set()
        # Session dismissal & False Positive feedback tracking
        self.dismissed_sessions = {}
        self.session_evaluations = {}

    def dismiss_session(self, session_id: str, reason: str = "False positive dismissed by operator", operator_id: str = "operator") -> dict:
        """
        Unlocks a latched session and records false positive feedback (Human-in-the-Loop).
        """
        was_enforced = session_id in self.enforced_sessions
        if was_enforced:
            self.enforced_sessions.remove(session_id)
            
        record = {
            "session_id": session_id,
            "dismissed_at": time.time(),
            "reason": reason,
            "operator_id": operator_id,
            "previous_enforced": was_enforced
        }
        self.dismissed_sessions[session_id] = record
        return {
            "success": True,
            "session_id": session_id,
            "status": "DISMISSED",
            "audit_record": record
        }

    async def evaluate_meeting_step(self, session_id: str, pcm_bytes: bytes, transcript_text: str, erp_context: dict) -> dict:
        """
        Orchestrates parallel execution of Acoustic, Coercion, and DoA evaluation.
        Calculates a dynamic risk score and enforces actions if the score exceeds the safe threshold.
        Includes contextual cross-validation to mitigate False Positives.
        """
        start_time = time.time()
        
        # If session has already been dismissed by an operator, suppress repeated enforcement
        is_previously_dismissed = session_id in self.dismissed_sessions
        
        # FR-1: Parallel Analyze
        # acoustic_agent.evaluate_pcm_artifacts is async
        acoustic_task = asyncio.create_task(self.acoustic_agent.evaluate_pcm_artifacts(pcm_bytes))
        
        # coercion_agent.evaluate_intent is async
        coercion_task = asyncio.create_task(self.coercion_agent.evaluate_intent(transcript_text))
        
        # doa_agent is expected to have verify_treasury_policy (either module or class with the method)
        # It's a sync function, so we run it in a thread
        doa_verify = getattr(self.doa_agent, "verify_treasury_policy", None)
        if not doa_verify:
            # Fallback if it's passed directly as a function or module doesn't match
            from app.agents.coercion.doa_agent import verify_treasury_policy
            doa_verify = verify_treasury_policy
            
        doa_task = asyncio.create_task(asyncio.to_thread(
            doa_verify, 
            erp_context.get("operator_id", ""), 
            erp_context.get("amount", 0.0), 
            erp_context.get("beneficiary", "")
        ))

        import os
        sla_timeout = float(os.environ.get("SLA_TIMEOUT_SUPERVISOR", "0.75"))
        
        tasks = [acoustic_task, coercion_task, doa_task]
        a_score, c_score, d_score = 0.0, 0.0, 0.0
        
        # Fast-Fail Evaluation Loop
        start_wait = time.time()
        while tasks and (time.time() - start_wait) < sla_timeout:
            remaining_time = max(0.1, sla_timeout - (time.time() - start_wait))
            done, pending = await asyncio.wait(
                tasks, 
                timeout=remaining_time,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            if not done:
                break
                
            for t in done:
                try:
                    res = t.result()
                except Exception:
                    res = {}
                    
                if t == acoustic_task:
                    a_score = res.get("acoustic_score", 0.0)
                elif t == coercion_task:
                    c_score = res.get("coercion_score", 0.0)
                elif t == doa_task:
                    d_score = res.get("doa_violation_score", 0.0)
            
            # Short-circuit logic: If any factor is extremely high, stop waiting
            if a_score >= 0.90 or c_score >= 0.90 or d_score >= 0.90:
                print("\n[⚡ FAST-FAIL] Critical risk detected! Short-circuiting remaining tasks...")
                for t in pending:
                    t.cancel()
                pending = set()
                break
                
            tasks = list(pending)

        # Enforce timeout: Cancel any agent that violates the SLA
        for t in pending:
            t.cancel()

        # FR-2: Dynamic Risk Synthesis Formula
        # RiskScore = 0.45 * AcousticScore + 0.35 * CoercionScore + 0.20 * DoAViolationScore
        total_risk = round(0.45 * a_score + 0.35 * c_score + 0.20 * d_score, 3)
        
        # False Positive Mitigation & Contextual Cross-Validation:
        # Isolated single-agent spikes without corroboration are subject to attenuation:
        # - If Coercion is high but Acoustic voice is natural (<0.3) AND DoA is whitelisted/compliant (==0.0),
        #   it may be legitimate operational urgency (False Positive candidate).
        # - If Acoustic has an isolated spike but Coercion (<0.2) and DoA (==0.0) are completely clean,
        #   it may be telecommunication codec packet loss or mic noise.
        is_isolated_coercion = (c_score >= 0.90 and a_score < 0.30 and d_score == 0.0)
        is_isolated_acoustic = (a_score >= 0.90 and c_score < 0.20 and d_score == 0.0)
        
        mitigation_applied = False
        mitigation_reason = None
        
        if is_isolated_coercion:
            mitigation_applied = True
            mitigation_reason = "Isolated urgency detected: Whitelisted beneficiary and natural voice suggest legitimate operational business request. Scaled to WARNING."
            total_risk = 0.65
        elif is_isolated_acoustic:
            mitigation_applied = True
            mitigation_reason = "Isolated acoustic anomaly: Zero coercion signals and compliant DoA suggest network/codec noise. Scaled to WARNING."
            total_risk = 0.65
        elif a_score >= 0.90 or c_score >= 0.90 or d_score >= 0.90:
            # Genuine Multi-factor or severe DoA breach Fast-Fail:
            total_risk = max(total_risk, 0.95)

        # If manually dismissed by operator previously, downgrade status
        if is_previously_dismissed:
            decision_status = "OVERRIDDEN_DISMISSED"
        elif total_risk < 0.6:
            decision_status = "NORMAL"
        elif total_risk <= 0.85:
            decision_status = "WARNING"
        else:
            decision_status = "CRITICAL"

        decision = {
            "session_id": session_id,
            "risk_score": total_risk,
            "breakdown": {"acoustic": a_score, "coercion": c_score, "doa": d_score},
            "status": decision_status,
            "false_positive_mitigation": {
                "applied": mitigation_applied,
                "reason": mitigation_reason,
                "is_previously_dismissed": is_previously_dismissed
            }
        }

        # FR-3 & FR-4: Barge-in Trigger Dispatcher & State Latching
        # Only enforce if not previously dismissed and not already enforced
        if total_risk > 0.85 and session_id not in self.enforced_sessions and not is_previously_dismissed:
            self.enforced_sessions.add(session_id)
            reason = f"Voice Clone ({int(a_score*100)}%), Coercion ({int(c_score*100)}%), DoA Breach ({int(d_score*100)}%)"
            
            # Trigger Voice Barge-in and Lock Event simultaneously
            if inspect.iscoroutinefunction(self.barge_in_handler):
                b_task = self.barge_in_handler(session_id, total_risk, reason)
            else:
                b_task = asyncio.to_thread(self.barge_in_handler, session_id, total_risk, reason)
                
            if inspect.iscoroutinefunction(self.broadcast_handler):
                br_task = self.broadcast_handler(session_id, reason, total_risk)
            else:
                br_task = asyncio.to_thread(self.broadcast_handler, session_id, reason, total_risk)
                
            await asyncio.gather(b_task, br_task)

        end_time = time.time()
        decision["latency_ms"] = round((end_time - start_time) * 1000, 2)
        self.session_evaluations[session_id] = decision
        
        return decision
