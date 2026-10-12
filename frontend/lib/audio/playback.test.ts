import { describe, expect, it, vi } from "vitest";
import { BargeInAudioPlayer, base64ToFloat32, parseBargeInFrame } from "./playback";

function b64(bytes: number[]) {
  return btoa(String.fromCharCode(...bytes));
}

function fakeContext(initialTime = 0) {
  const sources: { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; buffer: unknown }[] = [];
  const ctx = {
    state: "suspended" as string,
    currentTime: initialTime,
    destination: {},
    resume: vi.fn(async () => {
      ctx.state = "running";
    }),
    createBuffer: vi.fn((channels: number, length: number, rate: number) => ({
      duration: length / rate,
      length,
      sampleRate: rate,
      getChannelData: () => new Float32Array(length),
    })),
    createBufferSource: vi.fn(() => {
      const source = {
        buffer: null as unknown,
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null as null | (() => void),
      };
      sources.push(source);
      return source;
    }),
  };
  return { ctx, sources };
}

function makePlayer(initialTime = 0) {
  const { ctx, sources } = fakeContext(initialTime);
  const factory = vi.fn(() => ctx as unknown as AudioContext);
  return { player: new BargeInAudioPlayer({ audioContextFactory: factory }), ctx, sources, factory };
}

describe("base64ToFloat32", () => {
  it("decodes little-endian 16-bit PCM to floats in [-1, 1)", () => {
    const out = base64ToFloat32(b64([0x00, 0x7f]));
    expect(out[0]).toBeCloseTo(32512 / 32768, 6); // 0x7F00
    const neg = base64ToFloat32(b64([0x00, 0x80]));
    expect(neg[0]).toBe(-1);
  });

  it("drops a trailing half sample instead of throwing", () => {
    expect(base64ToFloat32(b64([0x01, 0x00, 0x02])).length).toBe(1);
  });

  it("returns an empty array for empty or invalid input", () => {
    expect(base64ToFloat32("").length).toBe(0);
    expect(base64ToFloat32("***not base64***").length).toBe(0);
  });
});

describe("parseBargeInFrame", () => {
  it("returns the base64 payload of a valid 24 kHz frame", () => {
    const text = JSON.stringify({ type: "BARGE_IN_AUDIO", audio: "AAA=", sampleRate: 24000 });
    expect(parseBargeInFrame(text)).toBe("AAA=");
  });

  it.each([
    "not json",
    JSON.stringify({ type: "LOCK_SESSION" }),
    JSON.stringify({ type: "BARGE_IN_AUDIO", audio: 5, sampleRate: 24000 }),
    JSON.stringify({ type: "BARGE_IN_AUDIO", audio: "AAA=", sampleRate: 16000 }),
    JSON.stringify([]),
  ])("ignores %s", (text) => {
    expect(parseBargeInFrame(text)).toBeNull();
  });
});

describe("BargeInAudioPlayer", () => {
  it("creates the context at 24 kHz lazily and resumes it on unlock", async () => {
    const { player, ctx, factory } = makePlayer();
    expect(factory).not.toHaveBeenCalled();
    await player.unlock();
    expect(ctx.resume).toHaveBeenCalled();
    expect(ctx.state).toBe("running");
  });

  it("builds a 24 kHz mono buffer and starts the first chunk immediately", async () => {
    const { player, ctx, sources } = makePlayer(5);
    await player.playChunk(b64([0, 0, 0, 0, 0, 0, 0, 0])); // 4 samples
    expect(ctx.createBuffer).toHaveBeenCalledWith(1, 4, 24000);
    expect(sources[0].start).toHaveBeenCalledWith(5);
  });

  it("schedules chunks back to back with no gap or overlap", async () => {
    const { player, sources } = makePlayer(0);
    const chunk = b64(new Array(480).fill(0)); // 240 samples = 10 ms
    await player.playChunk(chunk);
    await player.playChunk(chunk);
    await player.playChunk(chunk);
    const starts = sources.map((s) => s.start.mock.calls[0][0] as number);
    expect(starts[1]).toBeCloseTo(starts[0] + 0.01, 9);
    expect(starts[2]).toBeCloseTo(starts[1] + 0.01, 9);
  });

  it("restarts from currentTime after an underrun instead of scheduling in the past", async () => {
    const { player, ctx, sources } = makePlayer(0);
    const chunk = b64(new Array(480).fill(0));
    await player.playChunk(chunk);
    ctx.currentTime = 10;
    await player.playChunk(chunk);
    expect(sources[1].start).toHaveBeenCalledWith(10);
  });

  it("ignores empty chunks", async () => {
    const { player, sources } = makePlayer();
    await player.playChunk("");
    expect(sources).toHaveLength(0);
  });

  it("stopAll silences scheduled audio, resets the queue and still plays afterwards", async () => {
    const { player, ctx, sources } = makePlayer(0);
    const chunk = b64(new Array(480).fill(0));
    await player.playChunk(chunk);
    await player.playChunk(chunk);
    player.stopAll();
    expect(sources[0].stop).toHaveBeenCalled();
    expect(sources[1].stop).toHaveBeenCalled();
    ctx.currentTime = 1;
    await player.playChunk(chunk);
    expect(sources[2].start).toHaveBeenCalledWith(1);
  });

  it("stopAll before any audio is a no-op", () => {
    const { player } = makePlayer();
    expect(() => player.stopAll()).not.toThrow();
  });

  it("a chunk still waiting for the context to resume is dropped by stopAll", async () => {
    const { player, ctx, sources } = makePlayer(0);
    let release: () => void = () => undefined;
    ctx.resume.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          release = () => {
            ctx.state = "running";
            resolve();
          };
        }),
    );
    const pending = player.playChunk(b64(new Array(480).fill(0)));
    player.stopAll();
    release();
    await pending;
    expect(sources).toHaveLength(0);
  });
});
