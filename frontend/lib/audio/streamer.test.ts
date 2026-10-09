import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EchoAudioStreamer, attachMeetingLifecycle } from "./streamer";

class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  static CLOSED = 3;
  readyState = 0;
  binaryType = "blob";
  bufferedAmount = 0;
  sent: (string | ArrayBuffer)[] = [];
  closedWith: [number?, string?] | null = null;
  onopen: null | (() => void) = null;
  onerror: null | ((e: unknown) => void) = null;
  onclose: null | ((e: { code: number }) => void) = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }
  close(code?: number, reason?: string) {
    this.closedWith = [code, reason];
    this.readyState = FakeSocket.CLOSED;
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
  drop(code = 1006) {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.({ code });
  }
  fail() {
    this.onerror?.(new Event("error"));
    this.drop(1006);
  }
}

const last = () => FakeSocket.instances[FakeSocket.instances.length - 1];
const chunk = () => new ArrayBuffer(3200);

function make(opts = {}) {
  return new EchoAudioStreamer("ws://test/ws/audio", "sess-1", {
    webSocketImpl: FakeSocket as unknown as typeof WebSocket,
    ...opts,
  });
}

async function connected(opts = {}) {
  const s = make(opts);
  const p = s.connect();
  last().open();
  await p;
  return s;
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeSocket);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("handshake", () => {
  it("sends INIT_SESSION first, as text, before any audio", async () => {
    const s = await connected();
    const first = JSON.parse(last().sent[0] as string);
    expect(first).toMatchObject({
      type: "INIT_SESSION",
      sessionId: "sess-1",
      audioConfig: { encoding: "LINEAR16", sampleRate: 16000, channels: 1, chunkDurationMs: 100 },
    });
    expect(typeof first.timestamp).toBe("number");
    expect(last().binaryType).toBe("arraybuffer");
    expect(s.state).toBe("CONNECTED");
  });

  it("refuses audio before the socket is open", () => {
    const s = make();
    void s.connect();
    expect(s.sendAudioChunk(chunk())).toBe(false);
    expect(last().sent).toHaveLength(0);
  });

  it("rejects connect() when the socket errors before opening, without auto-retrying", async () => {
    const s = make();
    const p = s.connect();
    const rejected = expect(p).rejects.toBeDefined();
    last().fail();
    await rejected;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});

describe("congestion control", () => {
  it("sends binary frames when the buffer is healthy", async () => {
    const s = await connected();
    const buf = chunk();
    expect(s.sendAudioChunk(buf)).toBe(true);
    expect(last().sent[1]).toBe(buf);
  });

  it("drops the chunk and warns above 64 KB buffered", async () => {
    const onBufferWarning = vi.fn();
    const s = await connected({ onBufferWarning });
    last().bufferedAmount = 70_000;
    expect(s.sendAudioChunk(chunk())).toBe(false);
    expect(last().sent).toHaveLength(1); // only the handshake
    expect(onBufferWarning).toHaveBeenCalledWith(70_000);
  });

  it("still sends at exactly 64 KB", async () => {
    const s = await connected();
    last().bufferedAmount = 64 * 1024;
    expect(s.sendAudioChunk(chunk())).toBe(true);
  });
});

describe("graceful shutdown", () => {
  it("sends STOP_STREAM last and closes with 1000", async () => {
    const s = await connected();
    s.gracefulDisconnect("USER_STOPPED");
    const sock = FakeSocket.instances[0];
    const stop = JSON.parse(sock.sent[sock.sent.length - 1] as string);
    expect(stop).toMatchObject({ type: "STOP_STREAM", sessionId: "sess-1", reason: "USER_STOPPED" });
    expect(sock.closedWith?.[0]).toBe(1000);
    expect(s.state).toBe("DISCONNECTED");
  });

  it("is safe to call twice and before connecting", async () => {
    make().gracefulDisconnect();
    const s = await connected();
    s.gracefulDisconnect();
    expect(() => s.gracefulDisconnect()).not.toThrow();
  });

  it("does not reconnect after a deliberate close", async () => {
    const s = await connected();
    s.gracefulDisconnect();
    FakeSocket.instances[0].drop(1000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("cancels a pending reconnect timer (no zombie socket afterwards)", async () => {
    const s = await connected();
    last().drop(1006);
    expect(s.state).toBe("RECONNECTING");
    s.gracefulDisconnect();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(s.state).toBe("DISCONNECTED");
  });
});

describe("reconnect", () => {
  it("retries after 1s, 2s, 4s, re-sends INIT_SESSION, then gives up", async () => {
    const onStateChange = vi.fn();
    const s = await connected({ onStateChange });
    last().drop(1006);
    expect(s.state).toBe("RECONNECTING");

    await vi.advanceTimersByTimeAsync(999);
    expect(FakeSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(2);
    last().open();
    expect(JSON.parse(last().sent[0] as string).type).toBe("INIT_SESSION");
    expect(s.state).toBe("CONNECTED");

    // Attempt counter resets after a successful reopen.
    last().drop(1006);
    await vi.advanceTimersByTimeAsync(1000);
    expect(FakeSocket.instances).toHaveLength(3);
    last().fail();
    await vi.advanceTimersByTimeAsync(2000);
    expect(FakeSocket.instances).toHaveLength(4);
    last().fail();
    await vi.advanceTimersByTimeAsync(4000);
    expect(FakeSocket.instances).toHaveLength(5);
    last().fail();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.instances).toHaveLength(5);
    expect(s.state).toBe("DISCONNECTED");
    expect(onStateChange).toHaveBeenCalledWith("RECONNECTING");
  });

  it.each([1008, 1009, 1013])("does not retry a policy close (%i)", async (code) => {
    const s = await connected();
    last().drop(code);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(s.state).toBe("ERROR");
  });

  it("does not reconnect after a server-side normal close", async () => {
    const s = await connected();
    last().drop(1000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(s.state).toBe("DISCONNECTED");
  });
});

describe("attachMeetingLifecycle", () => {
  it("sends STOP_STREAM and notifies when the track ends", async () => {
    const s = await connected();
    const track = { onended: null as null | (() => void) } as unknown as MediaStreamTrack;
    const done = vi.fn();
    attachMeetingLifecycle(track, s, done);
    track.onended!(new Event("ended"));
    const sock = FakeSocket.instances[0];
    expect(JSON.parse(sock.sent[sock.sent.length - 1] as string).type).toBe("STOP_STREAM");
    expect(done).toHaveBeenCalledTimes(1);
  });
});
