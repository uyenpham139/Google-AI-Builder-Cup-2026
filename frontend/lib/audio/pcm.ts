export const TARGET_SAMPLE_RATE = 16000;
export const CHUNK_SAMPLES = 1600; // 100 ms at 16 kHz

export function convertFloat32ToInt16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const raw = input[i];
    const s = Number.isNaN(raw) ? 0 : Math.max(-1, Math.min(1, raw));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}

export function computeRms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

/**
 * Box-filter downsampler that keeps its position between blocks, so feeding
 * 128-frame audio quanta gives the same result as one big buffer.
 */
export class Downsampler {
  private readonly ratio: number;
  private carry = new Float32Array(0);
  private frac = 0;

  constructor(inputRate: number, outputRate: number = TARGET_SAMPLE_RATE) {
    this.ratio = inputRate / outputRate;
  }

  process(input: Float32Array): Float32Array {
    if (this.ratio === 1) return input;
    const buf = new Float32Array(this.carry.length + input.length);
    buf.set(this.carry);
    buf.set(input, this.carry.length);

    const out: number[] = [];
    let start = this.frac;
    for (;;) {
      const a = Math.round(start);
      const b = Math.round(start + this.ratio);
      if (b > buf.length) break;
      let sum = 0;
      for (let i = a; i < b; i++) sum += buf[i];
      out.push(b > a ? sum / (b - a) : 0);
      start += this.ratio;
    }
    const keep = Math.min(Math.round(start), buf.length);
    this.carry = buf.slice(keep);
    this.frac = start - keep;
    return Float32Array.from(out);
  }
}

/** Accumulates Int16 samples and emits fixed-size ArrayBuffers (default 3200 bytes). */
export class PcmChunker {
  private readonly buf: Int16Array;
  private filled = 0;

  constructor(
    private readonly onChunk: (chunk: ArrayBuffer) => void,
    private readonly chunkSamples: number = CHUNK_SAMPLES,
  ) {
    this.buf = new Int16Array(chunkSamples);
  }

  push(samples: Int16Array): void {
    let i = 0;
    while (i < samples.length) {
      const n = Math.min(this.chunkSamples - this.filled, samples.length - i);
      this.buf.set(samples.subarray(i, i + n), this.filled);
      this.filled += n;
      i += n;
      if (this.filled === this.chunkSamples) {
        this.onChunk(this.buf.slice().buffer);
        this.filled = 0;
      }
    }
  }

  reset(): void {
    this.filled = 0;
  }
}
