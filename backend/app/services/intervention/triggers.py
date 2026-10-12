"""Context-injected activation of the Voice Intervenor (ECHO-23)."""
import logging
import re
from typing import Protocol

from app.prompts.intervenor_prompt import TRIGGER_PREFIX

logger = logging.getLogger(__name__)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\[\]]+")


class TextTurnSender(Protocol):
    async def send_text_turn(self, text: str) -> bool: ...


def build_barge_in_text(token: str, risk_score: float, violation_reason: str) -> str:
    # The reason comes from upstream agents; keep it from forging extra alert structure.
    reason = _CONTROL_RE.sub(" ", violation_reason).strip()[:200]
    return (
        f"{TRIGGER_PREFIX} token={token} RiskScore={risk_score:.2f}. Violation={reason}. "
        "KÍCH HOẠT LỆNH CAN THIỆP PHONG TỎA BẰNG GIỌNG NÓI NGAY LẬP TỨC!"
    )


async def inject_barge_in_trigger(client: TextTurnSender, token: str, risk_score: float, violation_reason: str) -> bool:
    """Send the hidden user turn that makes the Live model speak. Returns False if it was not delivered."""
    sent = await client.send_text_turn(build_barge_in_text(token, risk_score, violation_reason))
    if sent:
        logger.info("Injected SYSTEM ALERT trigger into the Live session")
    else:
        logger.error("Could not inject the barge-in trigger (session not connected)")
    return sent
