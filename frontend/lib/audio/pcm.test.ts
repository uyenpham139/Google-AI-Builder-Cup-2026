import { describe, expect, it, vi } from "vitest";
import {
  CHUNK_SAMPLES,
  Downsampler,
  PcmChunker,
  computeRms,
  convertFloat32ToInt16,
} from "./pcm";

describe("convertFloat32ToInt16", () => {
  it("maps the ticket's reference values", () => {
    const out = convertFloat32ToInt16(new Float32Array([0, 1, -1, 0.5, -0.5]));
    expect(Array.from(out)).toEqual([0, 32767, -32768, 16383, -16384]);
  });

  it("clamps out-of-range samples instead of wrapping", () => {
    const out = convertFloat32ToInt16(new Float32Array([2, -3]));
    expect(Array.from(out)).toEqual([32767, -32768]);
  });

  it("handles NaN as silence", () => {
    expect(Array.from(convertFloat32ToInt16(new Float32Array([NaN])))).toEqual([0]);
  });
});

describe("computeRms", () => {
  it("is 0 for silence and for empty input", () => {
    expect(computeRms(new Float32Array(10))).toBe(0);
    expect(computeRms(new Float32Array(0))).toBe(0);
  });

  it("is the amplitude for a constant signal", () => {
    expect(computeRms(new Float32Array(8).fill(0.5))).toBeCloseTo(0.5, 6);
  });
});

describe("Downsampler", () => {
  it("turns 480 samples at 48 kHz into 160 at 16 kHz", () => {
    expect(new Downsampler(48000).process(new Float32Array(480)).length).toBe(160);
  });

  it("passes 16 kHz through untouched", () => {
    const input = new Float32Array([0.1, 0.2]);
    expect(new Downsampler(16000).process(input)).toBe(input);
  });

  it("averages each window", () => {
    const out = new Downsampler(48000).process(new Float32Array([0.3, 0.6, 0.9, 1, 1, 1]));
    expect(out[0]).toBeCloseTo(0.6, 5);
    expect(out[1]).toBeCloseTo(1, 5);
  });

  it("produces the same total across 128-frame blocks as in one shot (no drift)", () => {
    const signal = new Float32Array(48000).map((_, i) => Math.sin(i / 10));
    const oneShot = new Downsampler(48000).process(signal);
    const blocked = new Downsampler(48000);
    const parts: number[] = [];
    for (let i = 0; i < signal.length; i += 128) {
      parts.push(...blocked.process(signal.subarray(i, i + 128)));
    }
    expect(parts.length).toBe(oneShot.length);
    for (let i = 0; i < parts.length; i += 997) {
      expect(parts[i]).toBeCloseTo(oneShot[i], 5);
    }
  });

  it("converts 44.1 kHz to about one third of the sample count", () => {
    const out = new Downsampler(44100).process(new Float32Array(44100));
    expect(Math.abs(out.length - 16000)).toBeLessThanOrEqual(2);
  });
});

describe("PcmChunker", () => {
  it("emits 3200-byte buffers however the input is sliced", () => {
    const chunks: ArrayBuffer[] = [];
    const chunker = new PcmChunker((c) => chunks.push(c));
    const samples = new Int16Array(CHUNK_SAMPLES * 3 + 500).map((_, i) => i % 1000);
    for (let i = 0; i < samples.length; i += 333) {
      chunker.push(samples.subarray(i, i + 333));
    }
    expect(chunks).toHaveLength(3);
    expect(chunks.every((c) => c.byteLength === 3200)).toBe(true);
  });

  it("preserves sample order and values across chunk boundaries", () => {
    const chunks: ArrayBuffer[] = [];
    const chunker = new PcmChunker((c) => chunks.push(c), 4);
    chunker.push(new Int16Array([1, 2, 3]));
    chunker.push(new Int16Array([4, 5, 6, 7, 8]));
    expect(Array.from(new Int16Array(chunks[0]))).toEqual([1, 2, 3, 4]);
    expect(Array.from(new Int16Array(chunks[1]))).toEqual([5, 6, 7, 8]);
  });

  it("emits independent buffers (no aliasing of the internal buffer)", () => {
    const chunks: ArrayBuffer[] = [];
    const chunker = new PcmChunker((c) => chunks.push(c), 2);
    chunker.push(new Int16Array([1, 2]));
    chunker.push(new Int16Array([3, 4]));
    expect(Array.from(new Int16Array(chunks[0]))).toEqual([1, 2]);
  });

  it("reset discards a partial chunk", () => {
    const onChunk = vi.fn();
    const chunker = new PcmChunker(onChunk, 4);
    chunker.push(new Int16Array([1, 2, 3]));
    chunker.reset();
    chunker.push(new Int16Array([9]));
    expect(onChunk).not.toHaveBeenCalled();
  });
});
