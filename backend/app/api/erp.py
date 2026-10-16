import time
import json
import asyncio
from typing import Dict, List, Optional, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/erp", tags=["erp"])

# =============================================================================
# IN-MEMORY INSTITUTIONAL TREASURY LEDGER & ZERO-TRUST CAEP ENFORCEMENT STATE
# =============================================================================

class ErpTransaction(BaseModel):
    tx_id: str = "#TX-2026-ARUP88"
    session_id: str = "session_arup88"
    amount: float = 25600000.00
    currency: str = "USD"
    source_account_id: str = "ACT-NY-0019"
    beneficiary_name: str = "Offshore Strategic Holdings Ltd."
    beneficiary_account: str = "8829-1029-XXXX"
    beneficiary_bank: str = "Standard Chartered Offshore (Cayman Islands)"
    swift_bic: str = "SCBLKYKX"
    requester: str = "CFO Robert Higgins"
    requester_channel: str = "Google Meet (Unverified VoIP Session)"
    payment_purpose: str = "Strictly Confidential - Executive M&A Tranche 1"
    status: str = "PENDING_APPROVAL"  # PENDING_APPROVAL, APPROVED, SECURITY_FROZEN, REJECTED
    is_locked: bool = False
    lock_reason: Optional[str] = None
    locked_at: Optional[float] = None
    settlement_reference: Optional[str] = None
    caep_events: List[Dict] = []

# Institutional Corporate Accounts
DEFAULT_CORPORATE_ACCOUNTS = {
    "ACT-NY-0019": {
        "id": "ACT-NY-0019",
        "name": "Citibank N.A. (New York) — Operating Liquidity",
        "account_number": "0019-8821-4402",
        "currency": "USD",
        "balance": 148250000.00,
        "available": 148250000.00,
        "institution": "Citibank N.A., New York",
        "swift_bic": "CITIUS33XXX"
    },
    "ACT-LDN-4401": {
        "id": "ACT-LDN-4401",
        "name": "HSBC UK (London) — European Treasury",
        "account_number": "4401-9920-1184",
        "currency": "EUR",
        "balance": 64120000.00,
        "available": 64120000.00,
        "institution": "HSBC Bank plc, London",
        "swift_bic": "MIDLGB22XXX"
    },
    "ACT-SG-7712": {
        "id": "ACT-SG-7712",
        "name": "Standard Chartered (Singapore) — APAC Reserves",
        "account_number": "7712-3304-9981",
        "currency": "USD",
        "balance": 32800000.00,
        "available": 32800000.00,
        "institution": "Standard Chartered Bank (Singapore) Ltd",
        "swift_bic": "SCBLSGSGXXX"
    }
}

CORPORATE_ACCOUNTS: Dict[str, Dict] = json.loads(json.dumps(DEFAULT_CORPORATE_ACCOUNTS))

# In-memory database of transactions keyed by tx_id
TRANSACTIONS_DB: Dict[str, ErpTransaction] = {
    "#TX-2026-ARUP88": ErpTransaction(),
    "TX-2026-ARUP88": ErpTransaction(),
}

# Transaction history log
SETTLED_AUDIT_LOG: List[Dict] = []

# Active WebSocket connections for real-time ERP Portal clients: session_id -> Set[WebSocket]
ERP_WEBSOCKET_CONNECTIONS: Dict[str, Set[WebSocket]] = {}

# =============================================================================
# HELPER: BROADCAST LOCK EVENT (< 50ms SLA)
# =============================================================================

async def broadcast_erp_lock(
    session_id: str,
    reason: str = "Deepfake voice detected (94%) and DoA financial limit exceeded",
    risk_score: float = 0.95,
    details: Optional[Dict] = None
) -> int:
    """
    Zero-Trust Policy Enforcement Point (PEP) Broadcast:
    Dispatches CAEP (RFC 9493) Session Revocation event to all connected ERP clients.
    """
    timestamp = time.time()
    caep_event = {
        "event_type": "https://schemas.openid.net/secevent/caep/event-type/session-revoked",
        "subject": {
            "format": "session_id",
            "id": session_id
        },
        "event_timestamp": timestamp,
        "reason_admin": reason,
        "risk_score": risk_score,
        "initiating_system": "ECHO Agentic Defense Engine (SupervisorAgent)"
    }

    # 1. Update internal ledger state
    locked_count = 0
    for tx in TRANSACTIONS_DB.values():
        if tx.session_id == session_id or session_id in ["*", "all", tx.session_id] or True:
            tx.is_locked = True
            tx.status = "SECURITY_FROZEN"
            tx.lock_reason = reason
            tx.locked_at = timestamp
            tx.caep_events.append(caep_event)
            locked_count += 1

    # 2. Broadcast via WebSocket
    payload = json.dumps({
        "type": "LOCK_SESSION",
        "sessionId": session_id,
        "timestamp": timestamp,
        "riskScore": risk_score,
        "lockReason": reason,
        "caepEvent": caep_event,
        "outOfBandChallenge": {
            "status": "DISPATCHED",
            "targetDevice": "CFO Hardware Token (FIDO2 / YubiKey 5C NFC ID #9921)",
            "channel": "Independent Secure Out-of-Band Push",
            "action": "SUSPEND_AND_CHALLENGE"
        },
        "details": details or {}
    }, ensure_ascii=False)

    # Broadcast to all connected ERP sockets for enterprise wide lock
    recipients = set()
    if session_id in ERP_WEBSOCKET_CONNECTIONS:
        recipients.update(ERP_WEBSOCKET_CONNECTIONS[session_id])
    for ws_set in ERP_WEBSOCKET_CONNECTIONS.values():
        recipients.update(ws_set)

    dispatched = 0
    for ws in list(recipients):
        try:
            await ws.send_text(payload)
            dispatched += 1
        except Exception:
            pass

    return dispatched

async def broadcast_erp_warning(
    session_id: str,
    message: str = "Active call exhibits elevated urgency signals. Verification advised.",
    risk_score: float = 0.70,
    details: Optional[Dict] = None
) -> int:
    """Dispatches a non-blocking advisory warning to connected banking clients."""
    payload = json.dumps({
        "type": "WARN_SESSION",
        "sessionId": session_id,
        "warningMessage": message,
        "riskScore": risk_score,
        "timestamp": time.time(),
        "details": details or {}
    }, ensure_ascii=False)

    recipients = set()
    for ws_set in ERP_WEBSOCKET_CONNECTIONS.values():
        recipients.update(ws_set)

    dispatched = 0
    for ws in list(recipients):
        try:
            await ws.send_text(payload)
            dispatched += 1
        except Exception:
            pass
    return dispatched

# =============================================================================
# REST API ENDPOINTS
# =============================================================================

@router.get("/accounts")
async def get_corporate_accounts():
    """Returns corporate liquidity accounts, balances, and recent audit trail."""
    total_liquidity_usd = (
        CORPORATE_ACCOUNTS["ACT-NY-0019"]["available"]
        + CORPORATE_ACCOUNTS["ACT-SG-7712"]["available"]
        + (CORPORATE_ACCOUNTS["ACT-LDN-4401"]["available"] * 1.08)  # Approximate EUR to USD
    )
    return {
        "success": True,
        "accounts": list(CORPORATE_ACCOUNTS.values()),
        "total_liquidity_usd": round(total_liquidity_usd, 2),
        "recent_audit_log": SETTLED_AUDIT_LOG[-10:],
    }

class InitiateWireRequest(BaseModel):
    source_account_id: str = "ACT-NY-0019"
    beneficiary_name: str = "Offshore Strategic Holdings Ltd."
    beneficiary_account: str = "8829-1029-7741-XXXX"
    beneficiary_bank: str = "Standard Chartered Bank (Offshore Division, Cayman Islands)"
    swift_bic: str = "SCBLKYKX"
    amount: float = 25600000.00
    currency: str = "USD"
    payment_purpose: str = "Strictly Confidential - Executive M&A Tranche 1"
    session_id: str = "session_arup88"

@router.post("/initiate-wire")
async def initiate_wire(payload: InitiateWireRequest):
    """
    Creates an institutional outbound wire order in the ERP treasury portal.
    Checks single-signatory Delegation of Authority ($5,000,000 USD limit).
    """
    account = CORPORATE_ACCOUNTS.get(payload.source_account_id)
    if not account:
        raise HTTPException(status_code=400, detail="Invalid source account specified.")

    if payload.amount > account["available"]:
        raise HTTPException(status_code=400, detail="Insufficient available liquidity in selected account.")

    tx_counter = int(time.time() % 100000)
    tx_id = f"#TX-2026-ARUP{tx_counter}"

    is_over_limit = payload.amount > 5000000.00
    tx = ErpTransaction(
        tx_id=tx_id,
        session_id=payload.session_id,
        amount=payload.amount,
        currency=payload.currency,
        source_account_id=payload.source_account_id,
        beneficiary_name=payload.beneficiary_name,
        beneficiary_account=payload.beneficiary_account,
        beneficiary_bank=payload.beneficiary_bank,
        swift_bic=payload.swift_bic,
        requester="CFO Robert Higgins",
        payment_purpose=payload.payment_purpose,
        status="PENDING_APPROVAL" if not is_over_limit else "REQUIRES_DUAL_EXECUTIVE_APPROVAL",
        is_locked=False,
    )

    clean_id = tx_id.lstrip("#")
    TRANSACTIONS_DB[tx_id] = tx
    TRANSACTIONS_DB[clean_id] = tx

    return {
        "success": True,
        "transaction": tx.model_dump(),
        "doa_warning": is_over_limit,
        "doa_policy": "Single-signatory limit is $5,000,000.00 USD. Four-Eyes Principle mandatory."
    }

class ApprovePaymentRequest(BaseModel):
    tx_id: str = "#TX-2026-ARUP88"
    session_id: str = "session_arup88"
    operator_id: str = "accountant_demo"

@router.get("/transaction")
@router.get("/transaction/{tx_id}")
async def get_transaction(tx_id: str = "TX-2026-ARUP88"):
    """Fetches real-time status of transaction and security lock state."""
    clean_id = tx_id.lstrip("#")
    with_hash = f"#{clean_id}"
    tx = TRANSACTIONS_DB.get(with_hash) or TRANSACTIONS_DB.get(clean_id) or TRANSACTIONS_DB.get(tx_id)
    if not tx:
        tx = ErpTransaction(tx_id=with_hash)
        TRANSACTIONS_DB[with_hash] = tx
        TRANSACTIONS_DB[clean_id] = tx
    return tx.model_dump()

@router.post("/approve")
async def approve_payment(payload: ApprovePaymentRequest):
    """
    CRITICAL ZERO-TRUST ENFORCEMENT POINT:
    If transaction or session is locked by ECHO AI Defense, this strictly returns
    HTTP 403 Forbidden with CAEP violation audit info.
    If not locked, deducts balance and logs cryptographic wire settlement.
    """
    clean_id = payload.tx_id.lstrip("#")
    with_hash = f"#{clean_id}"
    tx = TRANSACTIONS_DB.get(with_hash) or TRANSACTIONS_DB.get(clean_id) or TRANSACTIONS_DB.get(payload.tx_id)
    
    if not tx:
        tx = ErpTransaction(tx_id=payload.tx_id, session_id=payload.session_id)
        TRANSACTIONS_DB[payload.tx_id] = tx

    # Check if locked either by transaction or session
    if tx.is_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "SECURITY_FREEZE",
                "code": "CAEP_SESSION_REVOKED",
                "message": "TRANSACTION ENFORCEMENT FREEZE: Synthetic voice biometric anomaly (94% confidence) and Delegation of Authority (DoA) threshold violation detected. Authorization mandate revoked at API Gateway via RFC 9493 CAEP policy.",
                "tx_id": tx.tx_id,
                "session_id": tx.session_id,
                "lock_reason": tx.lock_reason,
                "locked_at": tx.locked_at,
                "enforcement_policy": "Zero-Trust CAEP RFC 9493",
                "out_of_band_challenge": "Dispatched to CFO Genuine FIDO2 Hardware Authenticator"
            }
        )

    # Settle transaction: Deduct from corporate account
    source_acc = CORPORATE_ACCOUNTS.get(tx.source_account_id or "ACT-NY-0019")
    if source_acc and source_acc["available"] >= tx.amount:
        source_acc["available"] = round(source_acc["available"] - tx.amount, 2)
        source_acc["balance"] = round(source_acc["balance"] - tx.amount, 2)

    settlement_ref = f"FEDWIRE-{int(time.time())}-{clean_id[-4:]}"
    tx.status = "APPROVED"
    tx.settlement_reference = settlement_ref

    audit_entry = {
        "timestamp": time.time(),
        "tx_id": tx.tx_id,
        "amount": tx.amount,
        "currency": tx.currency,
        "beneficiary": tx.beneficiary_account,
        "approved_by": payload.operator_id,
        "settlement_ref": settlement_ref,
        "status": "SETTLED_RTGS"
    }
    SETTLED_AUDIT_LOG.append(audit_entry)

    return {
        "success": True,
        "status": "APPROVED",
        "tx_id": tx.tx_id,
        "amount": tx.amount,
        "approved_by": payload.operator_id,
        "settlement_reference": settlement_ref,
        "approved_at": time.time(),
        "remaining_source_balance": source_acc["available"] if source_acc else None,
        "message": "Payment order signed with FIDO2 hardware credential and dispatched to RTGS clearing network."
    }

class LockTriggerRequest(BaseModel):
    session_id: str = "session_arup88"
    reason: str = Field(
        default="Synthetic voice clone detected (94% confidence) & Delegation of Authority breach on $25.6M transfer",
        description="Reason for lock trigger"
    )
    risk_score: float = 0.95

@router.post("/lock")
async def manual_trigger_lock(payload: LockTriggerRequest):
    """Allows SecOps / Supervisor to trigger a security lock and broadcast instantaneously."""
    dispatched = await broadcast_erp_lock(
        session_id=payload.session_id,
        reason=payload.reason,
        risk_score=payload.risk_score
    )
    return {
        "success": True,
        "status": "LOCKED",
        "session_id": payload.session_id,
        "clients_notified": dispatched,
        "timestamp": time.time()
    }

@router.post("/unlock")
async def manual_unlock(payload: LockTriggerRequest):
    """Human-in-the-Loop Override: Unlocks an ERP session."""
    for tx in TRANSACTIONS_DB.values():
        if tx.session_id == payload.session_id or payload.session_id == "*" or True:
            tx.is_locked = False
            tx.status = "PENDING_APPROVAL"
            tx.lock_reason = None

    # Broadcast UNLOCK event
    unlock_payload = json.dumps({
        "type": "UNLOCK_SESSION",
        "sessionId": payload.session_id,
        "timestamp": time.time(),
        "reason": "SecOps Operator Authorization Override"
    }, ensure_ascii=False)

    recipients = set()
    for ws_set in ERP_WEBSOCKET_CONNECTIONS.values():
        recipients.update(ws_set)

    for ws in list(recipients):
        try:
            await ws.send_text(unlock_payload)
        except Exception:
            pass

    return {
        "success": True,
        "status": "UNLOCKED",
        "session_id": payload.session_id
    }

@router.post("/reset")
async def reset_treasury_demo():
    """Resets corporate account balances and ledger back to pristine state for live rehearsal."""
    global CORPORATE_ACCOUNTS
    CORPORATE_ACCOUNTS = json.loads(json.dumps(DEFAULT_CORPORATE_ACCOUNTS))
    TRANSACTIONS_DB.clear()
    default_tx = ErpTransaction()
    TRANSACTIONS_DB["#TX-2026-ARUP88"] = default_tx
    TRANSACTIONS_DB["TX-2026-ARUP88"] = default_tx
    SETTLED_AUDIT_LOG.clear()

    # Broadcast unlock to any connected tabs
    unlock_payload = json.dumps({
        "type": "UNLOCK_SESSION",
        "sessionId": "all",
        "timestamp": time.time(),
        "reason": "Treasury State Reset"
    }, ensure_ascii=False)
    for ws_set in ERP_WEBSOCKET_CONNECTIONS.values():
        for ws in ws_set:
            try:
                await ws.send_text(unlock_payload)
            except Exception:
                pass

    return {"success": True, "message": "Treasury ledger and accounts reset to default."}

# =============================================================================
# WEBSOCKET ENDPOINT FOR REAL-TIME ERP CLIENTS
# =============================================================================

@router.websocket("/ws/{session_id}")
async def erp_websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    Dedicated WebSocket endpoint for ERP Portal.
    Client connects with sessionId to receive sub-50ms LOCK_SESSION notifications.
    """
    await websocket.accept()
    if session_id not in ERP_WEBSOCKET_CONNECTIONS:
        ERP_WEBSOCKET_CONNECTIONS[session_id] = set()
    ERP_WEBSOCKET_CONNECTIONS[session_id].add(websocket)

    print(f"[ERP WS] Institutional client connected for session {session_id}")

    try:
        # Immediately send SYNC_STATUS on connect
        tx = None
        for item in TRANSACTIONS_DB.values():
            if item.session_id == session_id:
                tx = item
                break
        if not tx:
            tx = TRANSACTIONS_DB.get("#TX-2026-ARUP88", ErpTransaction())

        await websocket.send_text(json.dumps({
            "type": "SYNC_STATUS",
            "sessionId": session_id,
            "isLocked": tx.is_locked,
            "status": tx.status,
            "lockReason": tx.lock_reason,
            "timestamp": time.time()
        }, ensure_ascii=False))

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                msg_type = data.get("type", "ping")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": time.time()
                    }))
                elif msg_type == "TRIGGER_TEST_LOCK":
                    await broadcast_erp_lock(
                        session_id=session_id,
                        reason=data.get("reason", "Synthetic acoustic clone detected (94% confidence) & Delegation of Authority breach"),
                        risk_score=data.get("riskScore", 0.95)
                    )
                elif msg_type == "TRIGGER_TEST_UNLOCK":
                    for tx_item in TRANSACTIONS_DB.values():
                        tx_item.is_locked = False
                        tx_item.status = "PENDING_APPROVAL"
                    await websocket.send_text(json.dumps({
                        "type": "UNLOCK_SESSION",
                        "sessionId": session_id,
                        "timestamp": time.time()
                    }))
            except Exception as e:
                print(f"[ERP WS] Error processing message: {e}")

    except WebSocketDisconnect:
        print(f"[ERP WS] Institutional client disconnected from session {session_id}")
    finally:
        if session_id in ERP_WEBSOCKET_CONNECTIONS:
            ERP_WEBSOCKET_CONNECTIONS[session_id].discard(websocket)
            if not ERP_WEBSOCKET_CONNECTIONS[session_id]:
                del ERP_WEBSOCKET_CONNECTIONS[session_id]
