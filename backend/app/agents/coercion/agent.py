import json
import os
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

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
        
    async def evaluate_intent(self, text_segment: str) -> dict:
        """
        Evaluate the coercion/manipulation intent from the text segment using Gemini Flash.
        Handles both Entity Extraction and Intent Scoring.
        """
        prompt = f"""
        You are a cybersecurity expert specializing in CEO/CFO Fraud and Social Engineering detection.
        Your task is to analyze the following conversation segment and do two things:
        1. Extract transaction details (amount, recipient, urgency level).
        2. Evaluate whether the conversation contains psychological manipulation or coercion tactics.
        
        The coercion tactics include:
        - URGENCY_PRESSURE: Creating extreme time pressure (urgent, immediately, before 5 PM).
        - FORCED_SECRECY: Requiring unusual secrecy (top secret, do not tell anyone, keep quiet).
        - BYPASS_FOUR_EYES: Requesting to bypass standard control procedures (skip dual-signature, approve it yourself, no need to wait).
        - AUTHORITY_INTIMIDATION: Using authority to threaten (demotion, firing, bear the consequences).
        
        Scoring Rules (coercion_score):
        - If any coercion tactic is clearly present, coercion_score >= 0.85
        - If it is a normal business conversation with no signs of fraud, coercion_score < 0.20
        
        Conversation segment: "{text_segment}"
        """
        try:
            response = self.gemini_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CoercionEvaluation,
                    temperature=0.1
                ),
            )
            
            result = json.loads(response.text)
            return {
                "coercion_score": round(result.get("coercion_score", 0.0), 2),
                "matched_tactics": result.get("matched_tactics", []),
                "entities": result.get("entities", {}),
                "raw_text": text_segment
            }
        except Exception as e:
            return {
                "error": str(e),
                "raw_text": text_segment
            }
