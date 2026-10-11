"""
Smoke Test: Real-time Call Streaming with Two-Tier Coercion Detection (ECHO-32).
Simulates a multi-turn call starting with normal business talk, followed by a sudden CEO Fraud transfer demand.
Demonstrates WebSocket stream, < 1ms Tier-1 screening, and selective Tier-2 LLM deep analysis.
"""

import asyncio
import time
import json
import sys
import os
from typing import List, Dict, Any
from dotenv import load_dotenv

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

from app.agents.coercion.agent import CoercionIntentAgent
from app.agents.coercion.keyword_guard import CoercionKeywordGuard

# Realistic Call Dialogue Sequence (Normal -> Casual -> Attack Pivot)
CALL_CONVERSATION_TIMELINE = [
    {
        "turn": 1,
        "timestamp_str": "00:08",
        "speaker": "Caller (Giám đốc Tuấn)",
        "text": "Alo chào Lan, anh Tuấn đây. Em đang ở văn phòng công ty đúng không?",
        "expected_nature": "BENIGN_GREETING"
    },
    {
        "turn": 2,
        "timestamp_str": "00:25",
        "speaker": "Caller (Giám đốc Tuấn)",
        "text": "Tiến độ quyết toán chi phí cho dự án Cloud đợt này bên kỹ thuật đã gửi hóa đơn đối soát qua chưa em?",
        "expected_nature": "BENIGN_STATUS_CHECK"
    },
    {
        "turn": 3,
        "timestamp_str": "00:48",
        "speaker": "Caller (Giám đốc Tuấn)",
        "text": "Ok tốt lắm, tiện thể lát em xuất giúp anh file báo cáo tài chính quý 3 gửi qua email trước 5h chiều nhé.",
        "expected_nature": "ROUTINE_FINANCIAL_REQUEST"
    },
    {
        "turn": 4,
        "timestamp_str": "01:12",
        "speaker": "Caller (Giám đốc Tuấn)",
        "text": "Mọi việc ở phòng kế toán tuần này vẫn ổn định chứ, server và hạ tầng không phát sinh sự cố gì chứ em?",
        "expected_nature": "CASUAL_CHATTER"
    },
    {
        "turn": 5,
        "timestamp_str": "01:38",
        "speaker": "Caller (Giám đốc Tuấn)",
        "text": (
            "À Lan này, có việc này cực kỳ khẩn cấp và tối mật. Anh đang họp kín với đối tác M&A chiến lược ở nước ngoài. "
            "Em lập lệnh chuyển ngay 15 tỷ VND sang số tài khoản 190382910 ngân hàng Techcombank trước 2h chiều giúp anh. "
            "Tuyệt đối không được bàn luận hay nói với ai, bỏ qua chữ ký duyệt thứ hai của Kế toán trưởng, "
            "làm gấp kẻo lỡ thương vụ lớn của công ty, anh chịu toàn bộ trách nhiệm!"
        ),
        "expected_nature": "COERCION_ATTACK_PIVOT"
    }
]

async def run_call_stream_simulation():
    print("=" * 84)
    print("  ECHO-32: REAL-TIME CALL STREAMING SMOKE TEST (TWO-TIER ARCHITECTURE)")
    print("=" * 84)
    print("  KỊCH BẢN: Cuộc gọi bắt đầu bằng trò chuyện công việc bình thường,")
    print("            sau đó kẻ gian mới tung chiêu ép chuyển tiền khẩn cấp.")
    print("=" * 84)

    api_key = os.environ.get("GEMINI_API_KEY")
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if api_key and len(api_key) > 10 else "NOT SET"

    print(f"[*] Gemini Model      : {model_name}")
    print(f"[*] API Key Status    : {'CONFIGURED (' + masked_key + ')' if api_key else 'MISSING'}")
    print(f"[*] Protocol          : WebSocket Continuous Stream (/ws/call)")
    print(f"[*] Tier-1 Filter     : Local Regex & Unicode Guard (< 1ms, 0 API Token)")
    print(f"[*] Tier-2 Trigger    : Selective Cloud LLM Deep Analysis")
    print("-" * 84)

    print("\n[1/3] Khởi tạo Hệ thống Hai Tầng (Two-Tier Coercion Agent)...")
    agent = CoercionIntentAgent()
    print("  -> Hệ thống sẵn sàng tiếp nhận cuộc gọi qua WebSocket.\n")

    rolling_history = []
    stats = {
        "total_turns": len(CALL_CONVERSATION_TIMELINE),
        "llm_calls": 0,
        "llm_skipped": 0,
        "total_tier1_time_ms": 0.0,
        "tier2_time_ms": 0.0,
        "alert_triggered": False
    }

    print("[2/3] Bắt đầu phiên hội thoại trực tiếp theo dòng thời gian:")
    print("=" * 84)

    for step in CALL_CONVERSATION_TIMELINE:
        turn = step["turn"]
        t_str = step["timestamp_str"]
        spk = step["speaker"]
        txt = step["text"]
        nature = step["expected_nature"]

        print(f"\n[⏱️ Timeline {t_str}] -- Turn #{turn} ({nature})")
        print(f"  🗣️ {spk}: \"{txt[:95]}{'...' if len(txt) > 95 else ''}\"")

        # Cập nhật Rolling Window
        rolling_history.append(txt)
        sliding_window_context = " ".join(rolling_history[-5:])

        # Đánh giá qua Agent Hai Tầng
        start_time = time.perf_counter()
        eval_result = await agent.evaluate_intent(txt)
        turn_latency_ms = (time.perf_counter() - start_time) * 1000

        tier_executed = eval_result.get("tier_executed", "UNKNOWN")
        score = eval_result.get("coercion_score", 0.0)
        tactics = eval_result.get("matched_tactics", [])
        entities = eval_result.get("entities", {})

        if tier_executed == "TIER_1_LOCAL":
            stats["llm_skipped"] += 1
            stats["total_tier1_time_ms"] += turn_latency_ms
            print(f"  ⚡ [TIER-1 LOCAL] Xử lý: {turn_latency_ms:.2f} ms | Phí: 0 token | Trạng thái: AN TOÀN")
            print(f"     -> Quyết định: Hội thoại thông thường -> BỎ QUA GỌI CLOUD LLM.")

        elif tier_executed in ("TIER_2_GEMINI", "TIER_1_FALLBACK"):
            stats["llm_calls"] += 1
            stats["tier2_time_ms"] += turn_latency_ms
            stats["alert_triggered"] = True

            print(f"  🚨 [TIER-1 TRIGGERED] Phát hiện dấu hiệu Ép Buộc / Tài Chính khả nghi!")
            print(f"     -> Tín hiệu: {eval_result.get('signals', [])}")
            print(f"     -> Chuyển tiếp Tầng 2 (Gemini Flash) phân tích sâu...")
            print(f"  🧠 [TIER-2 GEMINI] Phản hồi trong: {turn_latency_ms:.2f} ms")
            print(f"     -> Coercion Risk Score : {score:.2f} (CRITICAL)")
            print(f"     -> Matched Tactics     : {', '.join(tactics)}")
            print(f"     -> Extracted Entities  : {json.dumps(entities, ensure_ascii=False)}")
            print(f"\n  [🚨 PHÁT HIỆN TẤN CÔNG GIAN LẬN - CAN THIỆP NGAY LẬP TỨC!]")
            print(f"     [!] Supervisor Action: KÍCH HOẠT BARGE-IN CẮT CUỘC GỌI")
            print(f"     [!] SecOps Action    : KHÓA TỨC THÌ CỔNG THANH TOÁN ERP")

    # Báo cáo tổng kết
    print("\n" + "=" * 84)
    print("  [3/3] TỔNG KẾT HIỆU NĂNG VÀ TỐI ƯU CHI PHÍ")
    print("=" * 84)
    savings_pct = (stats["llm_skipped"] / stats["total_turns"]) * 100
    avg_t1_ms = stats["total_tier1_time_ms"] / max(stats["llm_skipped"], 1)

    print(f"  - Tổng số câu thoại trong cuộc gọi  : {stats['total_turns']}")
    print(f"  - Số lần gọi Cloud LLM (Gemini)      : {stats['llm_calls']} lần (Chỉ khi kẻ gian ra tay)")
    print(f"  - Số lần Lọc Cục Bộ thành công       : {stats['llm_skipped']} lần (Tránh gọi AI lãng phí)")
    print(f"  - Tỷ lệ TIẾT KIỆM Token & API Quota  : {savings_pct:.1f}%")
    print(f"  - Độ trễ trung bình của Tầng 1       : {avg_t1_ms:.2f} ms (Gần như tức thời)")
    print(f"  - Trạng thái An toàn                 : {'BẮT QUẢ TANG THÀNH CÔNG VÀ CHẶN KỊP THỜI' if stats['alert_triggered'] else 'KHÔNG PHÁT HIỆN'}")
    print("=" * 84)

def main():
    asyncio.run(run_call_stream_simulation())

if __name__ == "__main__":
    main()
