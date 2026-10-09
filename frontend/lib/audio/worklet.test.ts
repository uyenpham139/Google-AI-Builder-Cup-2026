import { beforeAll, describe, expect, it, vi } from "vitest";

type Processor = { port: { postMessage: ReturnType<typeof vi.fn> }; process(inputs: Float32Array[][]): boolean };
let ProcessorClass: new () => Processor;
let registeredName: string;
const registerProcessor = vi.fn();

beforeAll(async () => {
  vi.stubGlobal(
    "AudioWorkletProcessor",
    class {
      port = { postMessage: vi.fn() };
    },
  );
  vi.stubGlobal("registerProcessor", registerProcessor);
  // @ts-expect-error plain worklet script, not a module with types
  await import("../../public/echo-pcm-processor.js");
  registeredName = registerProcessor.mock.calls[0][0];
  ProcessorClass = registerProcessor.mock.calls[0][1];
});

describe("echo-pcm-processor", () => {
  it("registers under the expected name", () => {
    expect(registeredName).toBe("echo-pcm-processor");
  });

  it("averages stereo channels into mono", () => {
    const p = new ProcessorClass();
    const left = new Float32Array([1, 0.5, 0]);
    const right = new Float32Array([0, 0.5, -1]);
    expect(p.process([[left, right]])).toBe(true);
    const sent = p.port.postMessage.mock.calls[0][0] as Float32Array;
    expect(Array.from(sent)).toEqual([0.5, 0.5, -0.5]);
  });

  it("passes a mono channel through unchanged", () => {
    const p = new ProcessorClass();
    p.process([[new Float32Array([0.1, 0.2])]]);
    const sent = p.port.postMessage.mock.calls[0][0] as Float32Array;
    expect(sent[0]).toBeCloseTo(0.1, 6);
  });

  it("keeps running and posts nothing when there is no input", () => {
    const p = new ProcessorClass();
    expect(p.process([[]])).toBe(true);
    expect(p.process([])).toBe(true);
    expect(p.port.postMessage).not.toHaveBeenCalled();
  });
});
