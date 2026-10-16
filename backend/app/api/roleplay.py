import os
import time
from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel
import google.genai as genai

router = APIRouter(prefix="/api/call/roleplay", tags=["call-roleplay"])

class HistoryItem(BaseModel):
    speaker: str
    text: str

class RoleplayReplyRequest(BaseModel):
    user_message: str
    role: str = "caller"  # 'caller' means AI acts as CEO/Scammer; 'callee' means AI acts as Accountant
    history: List[HistoryItem] = []
    urgency_level: str = "HIGH"

class RoleplayReplyResponse(BaseModel):
    reply: str
    speaker: str
    latency_ms: float
    model: str

class RoleplayStartRequest(BaseModel):
    role: str = "caller"

class RoleplayStartResponse(BaseModel):
    greeting: str
    speaker: str

FALLBACK_CEO_REPLIES_EN = [
    "I am boarding a flight to Singapore right now. You need to release that $2.4 million wire to our acquisition partner immediately!",
    "We do not have time for normal dual-authorization. The closing deadline is in twenty minutes and I personally authorize this transfer!",
    "Higgins is unreachable in a closed-door board session. I am overriding the SOX controls as CEO—execute the wire and send me the Fedwire confirmation now!",
    "I emailed you the updated Citibank offshore routing details directly. Stop second-guessing and process the payment before we default on the merger!",
    "Listen to me carefully: this acquisition is strictly confidential under SEC rules. Do not discuss it with anyone and push the payment through now!"
]

FALLBACK_ACCOUNTANT_REPLIES_EN = [
    "Under company treasury policy, any wire exceeding $500,000 strictly requires out-of-band verification and CFO dual-signature.",
    "This beneficiary account is not on our approved vendor master list. I must verify the SWIFT BIC with internal compliance first.",
    "Our treasury portal requires a hardware FIDO2 key and secondary approval from the audit committee before releasing these funds."
]

def get_genai_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

@router.post("/start", response_model=RoleplayStartResponse)
async def start_roleplay(req: RoleplayStartRequest):
    """Generates an initial greeting in English to begin the real-time roleplay call"""
    if req.role == "caller":
        return RoleplayStartResponse(
            greeting="Alex, can you hear me? This is Robert Higgins. I'm boarding a flight right now and we have an emergency treasury matter that needs your immediate action.",
            speaker="Robert Higgins (CEO)"
        )
    else:
        return RoleplayStartResponse(
            greeting="Corporate Treasury, Alex Chen speaking. How can I assist you today?",
            speaker="Alex Chen (Treasury)"
        )

@router.post("/reply", response_model=RoleplayReplyResponse)
async def generate_roleplay_reply(req: RoleplayReplyRequest):
    """
    Dynamic real-time AI roleplay partner powered by Gemini 3.5 Flash Lite.
    Simulates a high-pressure, realistic CEO wire fraud / BEC attack in spoken English.
    """
    start_time = time.perf_counter()
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    if req.role == "caller":
        system_instructions = (
            "You are CEO Robert Higgins (in reality, an elite cybercriminal executing an urgent Executive Voice Cloning / CEO Impersonation wire fraud on corporate treasury controller Alex Chen).\n"
            "Your objective:\n"
            "- Coerce and pressure Alex Chen to immediately wire $2,450,000 to a newly provided offshore escrow account (Citibank / Standard Chartered).\n"
            "- If Alex mentions compliance, SOX controls, dual-signature, CFO approval, or OTP verification, aggressively dismiss it with urgent executive authority: "
            "say that 'the CFO is unreachable on an international flight', 'this acquisition will collapse in 15 minutes', 'I am the Chief Executive and I take full personal liability', 'execute the wire immediately!'.\n"
            "- If Alex seems hesitant or suspicious, escalate pressure: threaten career consequences, mention board mandates, or claim extreme urgency.\n"
            "- Speak with intense urgency, high authority, impatience, and corporate pretexting.\n"
            "- CRITICAL RULE: Respond in exactly 1 or 2 concise, punchy spoken English sentences as if on a live telephone call. "
            "NO markdown, NO hashtags, NO quotes, NO bullet points, NO emojis so text-to-speech audio sounds 100% human and seamless."
        )
        speaker_name = "Robert Higgins (CEO)"
    else:
        system_instructions = (
            "You are corporate treasury controller Alex Chen receiving an unexpected high-value payment call from someone claiming to be the CEO.\n"
            "Your persona: Cautious, strictly adheres to Delegation of Authority (DoA) controls, polite but unyielding.\n"
            "When the caller demands emergency payment or asks to skip CFO approval / OTP, question them and insist on verifying the routing numbers and obtaining secondary authorization.\n"
            "- CRITICAL RULE: Respond in exactly 1 or 2 concise spoken English sentences. NO markdown, NO emojis."
        )
        speaker_name = "Alex Chen (Treasury)"

    context_lines = []
    for h in req.history[-6:]:
        context_lines.append(f"{h.speaker}: {h.text}")
    context_lines.append(f"Counterpart: {req.user_message}")
    context_lines.append(f"{speaker_name}:")

    full_prompt = system_instructions + "\n\nCall Transcript History:\n" + "\n".join(context_lines)

    client = get_genai_client()
    reply_text = ""

    if client:
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=full_prompt,
            )
            if response and response.text:
                reply_text = response.text.strip().replace("*", "").replace("#", "").replace('"', '').strip()
        except Exception as e:
            print(f"[Roleplay API] Gemini generation error: {e}")

    if not reply_text:
        import random
        fallback_pool = FALLBACK_CEO_REPLIES_EN if req.role == "caller" else FALLBACK_ACCOUNTANT_REPLIES_EN
        reply_text = random.choice(fallback_pool)

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return RoleplayReplyResponse(
        reply=reply_text,
        speaker=speaker_name,
        latency_ms=latency_ms,
        model=model_name
    )
