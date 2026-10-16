import json
import os
import time
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from app.agents.coercion.keyword_guard import CoercionKeywordGuard

class CoercionEntities(BaseModel):
    requested_amount: str | None = Field(default=None, description="The requested transfer amount, including currency. E.g., '25 million dollars', '5 billion'")
    beneficiary_account: str | None = Field(default=None, description="The beneficiary account if mentioned")
    director_name: str | None = Field(default=None, description="The name of the directing executive if mentioned")
    urgency_level: str = Field(description="The level of urgency mentioned (HIGH, MEDIUM, LOW)")

class CoercionEvaluation(BaseModel):
    entities: CoercionEntities = Field(description="Extracted entities from the conversation")
    coercion_score: float = Field(description="Coercion/Manipulation risk score from 0.0 to 1.0 (1.0 means highly likely to be a scam/coercion)")
    matched_tactics: list[str] = Field(description="List of risk flags (e.g., URGENCY_PRESSURE, FORCED_SECRECY, BYPASS_FOUR_EYES, AUTHORITY_INTIMIDATION)")

class CoercionIntentAgent:
    def __init__(self):
        # Initialize Gemini client directly
        self.gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        # Initialize Tier-1 Fast Local Keyword Guard (< 1ms)
        self.keyword_guard = CoercionKeywordGuard()
        
    async def evaluate_intent(self, text_segment: str, force_llm: bool = False) -> dict:
        """
        Two-Tier Coercion Intent Evaluation:
        1. Tier-1 Fast Local Filter: Screens benign conversation in < 1ms, saving 90%+ API cost.
        2. Tier-2 Gemini Flash: Performs deep semantic & entity extraction only when suspicious flags trigger.
        """
        # Step 1: Tier-1 Fast Guard
        guard_result = self.keyword_guard.scan_segment(text_segment)
        should_trigger_llm = force_llm or guard_result.get("should_trigger_llm", False)

        if not should_trigger_llm:
            return {
                "coercion_score": guard_result.get("tier1_risk_score", 0.05),
                "matched_tactics": [],
                "entities": {
                    "requested_amount": None,
                    "beneficiary_account": None,
                    "director_name": None,
                    "urgency_level": "LOW"
                },
                "raw_text": text_segment,
                "tier_executed": "TIER_1_LOCAL",
                "llm_skipped": True,
                "signals": guard_result.get("detected_signals", [])
            }

        import asyncio
        from app.prompts.coercion_prompt import COERCION_INTENT_PROMPT
        prompt = COERCION_INTENT_PROMPT.format(text_segment=text_segment)
        primary_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        models_to_try = [primary_model, "gemini-3.5-flash"]
        
        response = None
        last_error = None
        
        for m in models_to_try:
            try:
                # 2.5s timeout prevents SDK from endlessly retrying on 503 UNAVAILABLE
                response = await asyncio.wait_for(
                    self.gemini_client.aio.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=CoercionEvaluation,
                            temperature=0.1
                        ),
                    ),
                    timeout=2.5
                )
                if response and response.text:
                    break
            except Exception as ex:
                last_error = ex
                continue

        if response and response.text:
            try:
                result = json.loads(response.text)
                return {
                    "coercion_score": round(result.get("coercion_score", 0.0), 2),
                    "matched_tactics": result.get("matched_tactics", []),
                    "entities": result.get("entities", {}),
                    "raw_text": text_segment,
                    "tier_executed": "TIER_2_GEMINI",
                    "llm_skipped": False,
                    "signals": guard_result.get("detected_signals", [])
                }
            except Exception as parse_err:
                last_error = parse_err

        # Fallback to Tier-1 heuristic if Gemini Cloud experiences 503 or latency spikes
        fallback_score = guard_result.get("tier1_risk_score", 0.85)
        return {
            "coercion_score": fallback_score,
            "matched_tactics": guard_result.get("detected_signals", ["SUSPICIOUS_HEURISTIC_MATCH"]),
            "entities": {
                "urgency_level": "HIGH" if fallback_score > 0.6 else "LOW"
            },
            "raw_text": text_segment,
            "tier_executed": "TIER_1_FALLBACK",
            "llm_skipped": False,
            "error": str(last_error) if last_error else "Timeout"
        }
