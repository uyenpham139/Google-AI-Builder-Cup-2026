'use client';

import { useEffect } from 'react';
import { API_URL, GUARD_CHANNEL, WS_URL } from './config';
import { useBank } from './store';

/**
 * Subscribes the bank portal to Echo's enforcement channel.
 * LOCK_SESSION / UNLOCK_SESSION events are pushed by the backend when the
 * call-monitoring agents detect (or an operator clears) a coercion attempt.
 */
export function useGuardConnection() {
  const setLock = useBank((s) => s.setLock);
  const setGuardOnline = useBank((s) => s.setGuardOnline);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let alive = true;

    const connect = () => {
      ws = new WebSocket(`${WS_URL}/api/erp/ws/${GUARD_CHANNEL}`);

      ws.onopen = () => setGuardOnline(true);

      ws.onmessage = (event) => {
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }

        if (data.type === 'LOCK_SESSION') {
          setLock({
            sessionId: String(data.sessionId ?? ''),
            reason: String(data.lockReason ?? ''),
            riskScore: Number(data.riskScore ?? 0),
            at: Date.now(),
          });
        } else if (data.type === 'SYNC_STATUS' && data.isLocked) {
          setLock({
            sessionId: String(data.sessionId ?? ''),
            reason: String(data.lockReason ?? ''),
            riskScore: 0,
            at: Date.now(),
          });
        } else if (data.type === 'UNLOCK_SESSION') {
          setLock(null);
        }
      };

      ws.onclose = () => {
        setGuardOnline(false);
        if (alive) retry = setTimeout(connect, 2000);
      };
    };

    connect();

    return () => {
      alive = false;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, [setLock, setGuardOnline]);
}

/** Server-side truth: is the ledger currently frozen by Echo? */
export async function isLedgerLocked(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/erp/transaction/TX-2026-ARUP88`, { cache: 'no-store' });
    if (!res.ok) return false;
    const data = await res.json();
    return Boolean(data.is_locked);
  } catch {
    return false;
  }
}

/** Human-in-the-loop override: record the false positive and release the lock. */
export async function releaseLock(sessionId: string, reason: string) {
  const body = JSON.stringify({ operator_id: 'treasury_operator', reason });
  const headers = { 'Content-Type': 'application/json' };

  if (sessionId) {
    await fetch(`${API_URL}/api/alerts/${sessionId}/dismiss`, { method: 'POST', headers, body }).catch(() => null);
  }
  await fetch(`${API_URL}/api/erp/unlock`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ session_id: sessionId || GUARD_CHANNEL, reason }),
  }).catch(() => null);

  useBank.getState().setLock(null);
}
