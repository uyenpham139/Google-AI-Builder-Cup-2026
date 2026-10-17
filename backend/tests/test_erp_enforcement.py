import pytest
import time
from fastapi.testclient import TestClient
from app.main import app
from app.api.erp import TRANSACTIONS_DB, ErpTransaction, broadcast_erp_lock

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_erp_db():
    """Reset mock ERP DB before each test."""
    TRANSACTIONS_DB.clear()
    tx = ErpTransaction(
        tx_id="#TX-2026-ARUP88",
        session_id="session_arup88",
        amount=25600000.00,
        currency="USD",
        beneficiary_account="8829-1029-XXXX",
        beneficiary_bank="Standard Chartered Offshore (Cayman Islands)",
        requester="CFO Robert Higgins",
        status="PENDING_APPROVAL",
        is_locked=False,
        lock_reason=None,
        caep_events=[]
    )
    TRANSACTIONS_DB["#TX-2026-ARUP88"] = tx
    TRANSACTIONS_DB["TX-2026-ARUP88"] = tx
    yield

def test_get_transaction_details():
    response = client.get("/api/erp/transaction/TX-2026-ARUP88")
    assert response.status_code == 200
    data = response.json()
    assert "#TX-2026-ARUP88" in data["tx_id"] or "TX-2026-ARUP88" in data["tx_id"]
    assert data["amount"] == 25600000.00
    assert data["is_locked"] is False
    assert data["status"] == "PENDING_APPROVAL"

def test_approve_payment_success_when_clean():
    response = client.post("/api/erp/approve", json={
        "tx_id": "#TX-2026-ARUP88",
        "session_id": "session_arup88",
        "operator_id": "accountant_alice"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "APPROVED"
    assert data["approved_by"] == "accountant_alice"

def test_lock_enforcement_returns_403_forbidden():
    # 1. Trigger security lock via API
    lock_res = client.post("/api/erp/lock", json={
        "session_id": "session_arup88",
        "reason": "Deepfake acoustic fingerprint (94%) and DoA limit violation",
        "risk_score": 0.96
    })
    assert lock_res.status_code == 200
    assert lock_res.json()["status"] == "LOCKED"

    # 2. Check transaction status
    tx_res = client.get("/api/erp/transaction/TX-2026-ARUP88")
    assert tx_res.status_code == 200
    assert tx_res.json()["is_locked"] is True
    assert tx_res.json()["status"] == "SECURITY_FROZEN"


    # 3. Attempt to approve payment -> MUST BE REJECTED WITH 403 FORBIDDEN
    approve_res = client.post("/api/erp/approve", json={
        "tx_id": "#TX-2026-ARUP88",
        "session_id": "session_arup88",
        "operator_id": "accountant_victim"
    })
    assert approve_res.status_code == 403
    err_data = approve_res.json()["detail"]
    assert err_data["error"] == "SECURITY_FREEZE"
    assert err_data["code"] == "CAEP_SESSION_REVOKED"
    assert "Deepfake" in err_data["lock_reason"]

def test_unlock_restores_pending_status():
    # Lock first
    client.post("/api/erp/lock", json={"session_id": "session_arup88"})
    assert TRANSACTIONS_DB["#TX-2026-ARUP88"].is_locked is True

    # Unlock (Operator override)
    unlock_res = client.post("/api/erp/unlock", json={"session_id": "session_arup88"})
    assert unlock_res.status_code == 200
    assert unlock_res.json()["status"] == "UNLOCKED"
    assert TRANSACTIONS_DB["#TX-2026-ARUP88"].is_locked is False

def test_erp_websocket_sub_50ms_broadcast():
    session_id = "session_arup88"
    with client.websocket_connect(f"/api/erp/ws/{session_id}") as websocket:
        # Initial sync message
        initial_msg = websocket.receive_json()
        assert initial_msg["type"] == "SYNC_STATUS"
        assert initial_msg["isLocked"] is False

        # Send test lock trigger from client
        start_time = time.perf_counter()
        websocket.send_json({
            "type": "TRIGGER_TEST_LOCK",
            "reason": "Test attack injection",
            "riskScore": 0.98
        })

        # Receive broadcast
        broadcast_msg = websocket.receive_json()
        latency_ms = (time.perf_counter() - start_time) * 1000

        assert broadcast_msg["type"] == "LOCK_SESSION"
        assert broadcast_msg["sessionId"] == session_id
        assert broadcast_msg["riskScore"] == 0.98
        assert broadcast_msg["outOfBandChallenge"]["status"] == "DISPATCHED"
        # NFR-1 latency check
        assert latency_ms < 50.0, f"Lockdown latency {latency_ms}ms exceeded 50ms SLA"
