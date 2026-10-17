"""
Tier-1 Fast Local Keyword & Heuristic Guard for Conversation Content (ECHO-32).
Executes locally in < 1ms with 0 API cost.
Filters benign business chatter and selectively triggers Tier-2 LLM deep analysis.
Supports both English and Vietnamese (Unicode-safe).
"""

import re
from typing import Dict, Any, List

class CoercionKeywordGuard:
    def __init__(self):
        # 1. Financial / Money Keywords (EN & VI)
        self.financial_terms = [
            r"transfer", r"wire", r"bank", r"account", r"beneficiary", r"offshore", r"remittance",
            r"dollar", r"usd", r"vnd", r"dong", r"billion", r"million", r"\$",
            r"chuyển tiền", r"chuyển khoản", r"chuyển ngay", r"giải ngân", r"thanh toán", 
            r"tài khoản", r"ngân hàng", r"số tiền", r"tỷ đồng", r"triệu đồng", r"tỷ", r"triệu"
        ]

        # 2. Urgency & Time Pressure (EN & VI)
        self.urgency_terms = [
            r"urgent", r"urgently", r"immediately", r"right now", r"asap", r"deadline", r"hurry",
            r"before\s+\d+", r"trước\s+\d+",
            r"gấp", r"khẩn", r"ngay lập tức", r"ngay bây giờ", r"ngay", r"liền", r"chậm trễ"
        ]

        # 3. Forced Secrecy & Discretion (EN & VI)
        self.secrecy_terms = [
            r"secret", r"confidential", r"tell no one", r"keep quiet", r"do not tell", r"classified",
            r"tuyệt mật", r"bí mật", r"giữ kín", r"đừng nói", r"không nói với ai", r"không nói ai", r"kín tiếng"
        ]

        # 4. Procedure Bypass & Four-Eyes Avoidance (EN & VI)
        self.bypass_terms = [
            r"bypass", r"skip", r"override", r"four-eyes", r"approve yourself", r"no need to wait",
            r"bỏ qua", r"miễn duyệt", r"tự duyệt", r"bỏ qua chữ ký", r"không cần chờ", r"bỏ qua quy trình", r"chữ ký duyệt thứ 2"
        ]

        # 5. Authority Intimidation & Threat (EN & VI)
        self.intimidation_terms = [
            r"ceo", r"director", r"cfo", r"executive", r"board", r"fired", r"terminate", r"consequences",
            r"giám đốc", r"tổng giám đốc", r"chủ tịch", r"sa thải", r"đuổi việc", r"kỷ luật", r"chịu trách nhiệm"
        ]

        # Compile regex unions (using case-insensitive search)
        self.re_financial = re.compile(r"|".join(self.financial_terms), re.IGNORECASE)
        self.re_urgency = re.compile(r"|".join(self.urgency_terms), re.IGNORECASE)
        self.re_secrecy = re.compile(r"|".join(self.secrecy_terms), re.IGNORECASE)
        self.re_bypass = re.compile(r"|".join(self.bypass_terms), re.IGNORECASE)
        self.re_intimidation = re.compile(r"|".join(self.intimidation_terms), re.IGNORECASE)

    def scan_segment(self, text: str) -> Dict[str, Any]:
        """
        Fast local evaluation (< 1ms).
        Returns whether Tier-2 LLM should be triggered and heuristic flags.
        """
        if not text or not text.strip():
            return {
                "should_trigger_llm": False,
                "tier1_risk_score": 0.0,
                "detected_signals": [],
                "reason": "Empty segment"
            }

        text_lower = text.lower()
        signals: List[str] = []

        has_financial = bool(self.re_financial.search(text_lower))
        has_urgency = bool(self.re_urgency.search(text_lower))
        has_secrecy = bool(self.re_secrecy.search(text_lower))
        has_bypass = bool(self.re_bypass.search(text_lower))
        has_intimidation = bool(self.re_intimidation.search(text_lower))

        if has_financial:
            signals.append("FINANCIAL_INDICATOR")
        if has_urgency:
            signals.append("URGENCY_SIGNAL")
        if has_secrecy:
            signals.append("SECRECY_SIGNAL")
        if has_bypass:
            signals.append("BYPASS_SIGNAL")
        if has_intimidation:
            signals.append("AUTHORITY_SIGNAL")

        pressure_count = sum([has_urgency, has_secrecy, has_bypass, has_intimidation])

        # Core logic:
        # Scam pattern = Financial action + Pressure / Secrecy / Bypass / Authority
        if has_financial and pressure_count >= 1:
            is_suspicious = True
            tier1_score = 0.50 + 0.12 * pressure_count
        elif has_bypass or (has_secrecy and has_intimidation):
            is_suspicious = True
            tier1_score = 0.65
        elif has_financial:
            # Benign financial topic (e.g. Q3 earnings review)
            is_suspicious = False
            tier1_score = 0.15
        else:
            is_suspicious = False
            tier1_score = 0.05

        return {
            "should_trigger_llm": is_suspicious,
            "tier1_risk_score": min(round(tier1_score, 2), 0.95),
            "detected_signals": signals,
            "reason": "Suspicious financial coercion detected -> FORWARD TO TIER-2 LLM" if is_suspicious else "Normal conversational content -> LLM SKIPPED"
        }
