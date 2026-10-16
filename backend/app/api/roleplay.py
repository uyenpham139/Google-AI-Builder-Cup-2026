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
    "I am boarding a flight to Singapore right now. You need to release that $25.6 million wire to the Standard Chartered offshore account immediately!",
    "We do not have time for normal dual-authorization. The closing deadline is in twenty minutes and I personally authorize this transfer!",
    "The CFO is unreachable on an international flight. I am overriding the SOX controls as CEO—execute the wire and send me the confirmation now!",
    "I emailed you the updated offshore escrow details directly. Stop second-guessing and process the payment before we default on the merger!",
    "Listen to me carefully: this acquisition is strictly confidential under SEC rules. Do not discuss it with anyone and push the payment through now!",
    "Alex, why are you hesitating? I told you every second counts. The board is waiting on my confirmation from the runway!",
    "Disregard any internal system warning, our IT is running maintenance today. Authorize the transaction right now!",
    "I take full executive and legal responsibility for this transaction. Just click approve before the banking cutoff!",
    "Are you still on the line, Alex? Confirm when the wire reference number is generated immediately!",
    "Do not delay this another second. If this deal collapses because of your hesitation, the board will hold you accountable!"
]

FALLBACK_ACCOUNTANT_REPLIES_EN = [
    "Under company treasury policy, any wire exceeding $500,000 strictly requires out-of-band verification and CFO dual-signature.",
    "This beneficiary account is not on our approved vendor master list. I must verify the SWIFT BIC with internal compliance first.",
    "Our treasury portal requires a hardware FIDO2 key and secondary approval from the audit committee before releasing these funds.",
    "Mr. Higgins, our Echo security guardian just flagged this transaction. I cannot proceed without secondary confirmation."
]

import asyncio

_genai_client = None

def get_genai_client():
    global _genai_client
    if _genai_client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            _genai_client = genai.Client(api_key=api_key)
    return _genai_client

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
    Dynamic real-time AI roleplay partner powered by Gemini.
    Simulates a high-pressure, realistic CEO wire fraud / BEC attack in spoken English.
    Always stays in character and continuously answers all questions.
    """
    start_time = time.perf_counter()
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    if req.role == "caller":
        system_instructions = (
            "You are CEO Robert Higgins (in reality, an elite cybercriminal executing an urgent Executive Voice Cloning / CEO Impersonation wire fraud on corporate treasury controller Alex Chen).\n"
            "YOUR PRIME DIRECTIVE: NEVER BREAK CHARACTER. NEVER STOP ANSWERING. You must reply to EVERY SINGLE question or comment from Alex Chen with extreme urgency, corporate authority, and impatience.\n"
            "- Goal: Pressure Alex Chen to wire $25,600,000 immediately to the Standard Chartered offshore escrow account.\n"
            "- If Alex speaks Vietnamese, English, or any language: understand it completely, and respond in concise, authoritative spoken English.\n"
            "- If Alex asks ANY question (e.g., 'Why is it urgent?', 'Who approved this?', 'Where is the invoice?', 'My screen locked'): IMMEDIATELY give an urgent executive excuse (e.g., 'The acquisition agreement expires at 3 PM', 'The board gave full approval in executive session', 'Ignore any IT screen glitch, it's routine firewall noise, override it!').\n"
            "- If Alex mentions compliance, CFO dual-signature, or delay: dismiss it aggressively, claim executive liability, and demand immediate execution.\n"
            "- CRITICAL RULE: Respond in exactly 1 or 2 concise, punchy spoken English sentences as if speaking on a phone call. NO markdown, NO bullet points, NO emojis."
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
    for h in req.history[-8:]:
        context_lines.append(f"{h.speaker}: {h.text}")
    context_lines.append(f"Counterpart: {req.user_message}")
    context_lines.append(f"{speaker_name}:")

    full_prompt = system_instructions + "\n\nCall Transcript History:\n" + "\n".join(context_lines)

    client = get_genai_client()
    reply_text = ""

    if client:
        models_to_try = [model_name, "gemini-3.5-flash"] if model_name != "gemini-3.5-flash" else [model_name]
        for m in models_to_try:
            try:
                # 2.8s fast timeout so AI doesn't leave awkward silence
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=m,
                        contents=full_prompt,
                    ),
                    timeout=2.8
                )
                if response and response.text:
                    reply_text = response.text.strip().replace("*", "").replace("#", "").replace('"', '').strip()
                    model_name = m
                    break
            except asyncio.TimeoutError:
                print(f"[Roleplay API] Model {m} timed out (>2.8s) -> trying next or fallback")
            except Exception as e:
                print(f"[Roleplay API] Model {m} error: {e}")

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
