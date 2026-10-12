import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { canApprove, connectLockdownChannel, parseLockMessage } from "./channel";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onmessage: null | ((e: { data: string }) => void) = null;
  onclose: null | (() => void) = null;
  closed = false;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  receive(payload: unknown) {
    this.onmessage?.({ data: typeof payload === "string" ? payload : JSON.stringify(payload) });
  }
  drop() {
    this.onclose?.();
  }
}

const lock = (over = {}) => ({
  type: "LOCK_SESSION",
  sessionId: "s1",
  riskScore: 0.94,
  lockReason: "Fake CFO Voice",
  acousticFlag: "94%",
  timestamp: 1,
  ...over,
});

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

function connect(onLock = vi.fn()) {
  const handle = connectLockdownChannel({
    url: "ws://test/ws/events",
    sessionId: "s1",
    onLock,
    webSocketImpl: FakeSocket as unknown as typeof WebSocket,
  });
  return { handle, onLock };
}

describe("parseLockMessage", () => {
  it("accepts a LOCK_SESSION for the session", () => {
    expect(parseLockMessage(JSON.stringify(lock()), "s1")?.riskScore).toBe(0.94);
  });

  it.each([
    "not json",
    JSON.stringify([]),
    JSON.stringify({ type: "BARGE_IN_AUDIO" }),
    JSON.stringify(lock({ sessionId: "other" })),
  ])("rejects %s", (text) => {
    expect(parseLockMessage(text, "s1")).toBeNull();
  });
});

describe("connectLockdownChannel", () => {
  it("connects with the session id in the query", () => {
    connect();
    expect(FakeSocket.instances[0].url).toBe("ws://test/ws/events?sessionId=s1");
  });

  it("reports the lock once, even if the message repeats", () => {
    const { onLock } = connect();
    FakeSocket.instances[0].receive(lock());
    FakeSocket.instances[0].receive(lock({ riskScore: 0.5 }));
    expect(onLock).toHaveBeenCalledTimes(1);
    expect(onLock.mock.calls[0][0].riskScore).toBe(0.94);
  });

  it("reconnects after a drop so a lock sent meanwhile is still delivered", () => {
    const { onLock } = connect();
    FakeSocket.instances[0].drop();
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1].receive(lock());
    expect(onLock).toHaveBeenCalledTimes(1);
  });

  it("stops reconnecting after close()", () => {
    const { handle } = connect();
    handle.close();
    FakeSocket.instances[0].drop();
    vi.advanceTimersByTime(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(FakeSocket.instances[0].closed).toBe(true);
  });

  it("ignores messages for other sessions", () => {
    const { onLock } = connect();
    FakeSocket.instances[0].receive(lock({ sessionId: "other" }));
    expect(onLock).not.toHaveBeenCalled();
  });
});

describe("canApprove", () => {
  it("is false once locked and cannot be flipped back by the caller", () => {
    expect(canApprove(null)).toBe(true);
    expect(canApprove(lock() as never)).toBe(false);
  });
});
