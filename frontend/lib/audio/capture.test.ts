import { afterEach, describe, expect, it, vi } from "vitest";
import { AudioCapture, AudioCaptureError, initDisplayMediaStream } from "./capture";

function fakeTrack(kind: string) {
  return { kind, stop: vi.fn(), onended: null as null | (() => void), readyState: "live" };
}

function fakeStream(audio: number, video = 1) {
  const audioTracks = Array.from({ length: audio }, () => fakeTrack("audio"));
  const videoTracks = Array.from({ length: video }, () => fakeTrack("video"));
  return {
    audioTracks,
    videoTracks,
    getAudioTracks: () => audioTracks,
    getVideoTracks: () => videoTracks,
    getTracks: () => [...audioTracks, ...videoTracks],
  };
}

function stubDisplayMedia(impl: () => Promise<unknown>) {
  vi.stubGlobal("navigator", { mediaDevices: { getDisplayMedia: vi.fn(impl) } });
}

afterEach(() => vi.unstubAllGlobals());

describe("initDisplayMediaStream", () => {
  it("requests audio with processing disabled and stops video tracks", async () => {
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const result = await initDisplayMediaStream();
    expect(result).toBe(stream);
    expect(stream.videoTracks[0].stop).toHaveBeenCalled();
    expect(stream.audioTracks[0].stop).not.toHaveBeenCalled();
    const call = (navigator.mediaDevices.getDisplayMedia as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.video).toBe(true);
    expect(call.audio).toMatchObject({ echoCancellation: false, noiseSuppression: false, autoGainControl: false });
  });

  it("throws NO_AUDIO_TRACK and stops everything when 'Share audio' was not ticked", async () => {
    const stream = fakeStream(0);
    stubDisplayMedia(async () => stream);
    await expect(initDisplayMediaStream()).rejects.toMatchObject({ code: "NO_AUDIO_TRACK" });
    expect(stream.videoTracks[0].stop).toHaveBeenCalled();
  });

  it("maps a denied or cancelled picker to PERMISSION_DENIED", async () => {
    stubDisplayMedia(async () => {
      throw new DOMException("denied", "NotAllowedError");
    });
    await expect(initDisplayMediaStream()).rejects.toMatchObject({ code: "PERMISSION_DENIED" });
  });

  it("reports UNSUPPORTED when getDisplayMedia is missing", async () => {
    vi.stubGlobal("navigator", {});
    const err = await initDisplayMediaStream().catch((e) => e);
    expect(err).toBeInstanceOf(AudioCaptureError);
    expect(err.code).toBe("UNSUPPORTED");
  });

  it("rethrows unexpected errors untouched", async () => {
    stubDisplayMedia(async () => {
      throw new Error("boom");
    });
    await expect(initDisplayMediaStream()).rejects.toThrow("boom");
  });
});

describe("AudioCapture pipeline", () => {
  function setupAudioGraph(sampleRate: number) {
    const port: { onmessage: null | ((e: { data: Float32Array }) => void) } = { onmessage: null };
    const nodes = { workletConnected: false, closed: false };
    class FakeContext {
      sampleRate = sampleRate;
      destination = {};
      audioWorklet = { addModule: vi.fn(async () => undefined) };
      createMediaStreamSource() {
        return { connect: () => ({ connect: () => undefined }), disconnect: vi.fn() };
      }
      createGain() {
        return { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
      }
      close = vi.fn(async () => {
        nodes.closed = true;
      });
    }
    class FakeWorkletNode {
      port = port;
      connect = vi.fn(() => {
        nodes.workletConnected = true;
        return { connect: vi.fn() };
      });
      disconnect = vi.fn();
    }
    class FakeMediaStream {
      constructor(public tracks: unknown[]) {}
    }
    vi.stubGlobal("AudioContext", FakeContext);
    vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
    vi.stubGlobal("MediaStream", FakeMediaStream);
    return { port, nodes };
  }

  it("emits exact 3200-byte chunks and levels from worklet blocks", async () => {
    const { port } = setupAudioGraph(16000);
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const chunks: ArrayBuffer[] = [];
    const levels: number[] = [];
    const capture = new AudioCapture({ onAudioChunk: (c) => chunks.push(c), onLevel: (l) => levels.push(l) });
    await capture.start();
    expect(capture.running).toBe(true);
    for (let i = 0; i < 25; i++) port.onmessage!({ data: new Float32Array(128).fill(0.25) });
    expect(chunks).toHaveLength(2); // 25 * 128 = 3200 samples = two 1600-sample chunks
    expect(chunks.every((c) => c.byteLength === 3200)).toBe(true);
    expect(levels[0]).toBeCloseTo(0.25, 5);
    await capture.stop();
  });

  it("downsamples when the browser locks the context to 48 kHz", async () => {
    const { port } = setupAudioGraph(48000);
    stubDisplayMedia(async () => fakeStream(1));
    const chunks: ArrayBuffer[] = [];
    const capture = new AudioCapture({ onAudioChunk: (c) => chunks.push(c) });
    await capture.start();
    for (let i = 0; i < 75; i++) port.onmessage!({ data: new Float32Array(128) }); // 9600 samples @ 48k = 3200 @ 16k
    expect(chunks.length).toBeGreaterThanOrEqual(1);
    expect(chunks.every((c) => c.byteLength === 3200)).toBe(true);
    await capture.stop();
  });

  it("fires onEnded and tears down when the user stops sharing", async () => {
    const { nodes } = setupAudioGraph(16000);
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const onEnded = vi.fn();
    const capture = new AudioCapture({ onAudioChunk: () => undefined, onEnded });
    await capture.start();
    stream.audioTracks[0].onended!();
    await vi.waitFor(() => expect(onEnded).toHaveBeenCalledTimes(1));
    expect(nodes.closed).toBe(true);
    expect(capture.running).toBe(false);
  });

  it("stop() is idempotent and stops the audio track", async () => {
    setupAudioGraph(16000);
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const capture = new AudioCapture({ onAudioChunk: () => undefined });
    await capture.start();
    await capture.stop();
    await capture.stop();
    expect(stream.audioTracks[0].stop).toHaveBeenCalled();
  });

  it("closes the AudioContext and stops tracks when the worklet fails to load", async () => {
    const { nodes } = setupAudioGraph(16000);
    class FailingContext {
      sampleRate = 16000;
      audioWorklet = { addModule: vi.fn(async () => Promise.reject(new Error("404"))) };
      close = vi.fn(async () => {
        nodes.closed = true;
      });
    }
    vi.stubGlobal("AudioContext", FailingContext);
    const stream = fakeStream(1);
    stubDisplayMedia(async () => stream);
    const capture = new AudioCapture({ onAudioChunk: () => undefined });
    await expect(capture.start()).rejects.toThrow("404");
    expect(nodes.closed).toBe(true);
    expect(stream.audioTracks[0].stop).toHaveBeenCalled();
    expect(capture.running).toBe(false);
  });
});
