// Client side of the lockdown broadcast (ECHO-25): the ERP portal listens for LOCK_SESSION.

export interface LockInfo {
  type: "LOCK_SESSION";
  sessionId: string;
  riskScore: number;
  lockReason: string;
  acousticFlag: string | null;
  timestamp: number;
}

export function parseLockMessage(text: string, sessionId: string): LockInfo | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const msg = data as Record<string, unknown>;
  if (msg.type !== "LOCK_SESSION" || msg.sessionId !== sessionId) return null;
  return {
    type: "LOCK_SESSION",
    sessionId,
    riskScore: typeof msg.riskScore === "number" ? msg.riskScore : 0,
    lockReason: typeof msg.lockReason === "string" ? msg.lockReason : "",
    acousticFlag: typeof msg.acousticFlag === "string" ? msg.acousticFlag : null,
    timestamp: typeof msg.timestamp === "number" ? msg.timestamp : Date.now(),
  };
}

/** The one place that decides whether a payment may be submitted. Locked means never. */
export function canApprove(lock: LockInfo | null): boolean {
  return lock === null;
}

export interface LockdownChannelOptions {
  url: string;
  sessionId: string;
  onLock: (lock: LockInfo) => void;
  webSocketImpl?: typeof WebSocket;
  reconnectDelayMs?: number;
}

export function connectLockdownChannel(opts: LockdownChannelOptions): { close(): void } {
  const Impl = opts.webSocketImpl ?? WebSocket;
  const delay = opts.reconnectDelayMs ?? 1000;
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  let locked = false;

  const open = () => {
    const ws = new Impl(`${opts.url}?sessionId=${encodeURIComponent(opts.sessionId)}`);
    socket = ws;
    ws.onmessage = (event: MessageEvent<string>) => {
      const lock = parseLockMessage(String(event.data), opts.sessionId);
      if (lock && !locked) {
        locked = true; // a lock is final: later messages cannot change it
        opts.onLock(lock);
      }
    };
    // The server re-sends the lock to a client that joins late, so reconnecting never misses it.
    ws.onclose = () => {
      if (closed) return;
      timer = setTimeout(open, delay);
    };
  };

  open();
  return {
    close() {
      closed = true;
      if (timer !== null) clearTimeout(timer);
      socket?.close();
    },
  };
}
