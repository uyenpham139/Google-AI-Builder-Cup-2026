// Downlink playback for the Voice Intervenor's barge-in speech (ECHO-24).
// Raw PCM 16-bit little-endian, 24 kHz, mono, arriving as base64 in "BARGE_IN_AUDIO" frames.

export const DOWNLINK_SAMPLE_RATE = 24000;

/** Decodes base64 PCM16 to floats in [-1, 1). A trailing half sample is dropped. */
export function base64ToFloat32(base64Pcm: string): Float32Array {
  let binary: string;
  try {
    binary = atob(base64Pcm);
  } catch {
    return new Float32Array(0);
  }
  const samples = Math.floor(binary.length / 2);
  const out = new Float32Array(samples);
  for (let i = 0; i < samples; i++) {
    const lo = binary.charCodeAt(2 * i);
    const hi = binary.charCodeAt(2 * i + 1);
    const value = (hi << 8) | lo;
    out[i] = (value >= 0x8000 ? value - 0x10000 : value) / 32768;
  }
  return out;
}

/** Returns the base64 audio of a valid BARGE_IN_AUDIO frame, or null for anything else. */
export function parseBargeInFrame(text: string): string | null {
  let frame: unknown;
  try {
    frame = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof frame !== "object" || frame === null) return null;
  const { type, audio, sampleRate } = frame as Record<string, unknown>;
  if (type !== "BARGE_IN_AUDIO" || typeof audio !== "string" || sampleRate !== DOWNLINK_SAMPLE_RATE) {
    return null;
  }
  return audio;
}

export interface BargeInPlayerOptions {
  audioContextFactory?: () => AudioContext;
}

/**
 * Plays chunks back to back by scheduling each one at the end of the previous one on the
 * audio clock, so there are no gaps or clicks. The first chunk starts as soon as it arrives.
 */
export class BargeInAudioPlayer {
  private ctx: AudioContext | null = null;
  private nextPlayTime = 0;
  private active = new Set<AudioBufferSourceNode>();
  private generation = 0; // bumped by stopAll so chunks that were already in flight are dropped

  constructor(private readonly opts: BargeInPlayerOptions = {}) {}

  private context(): AudioContext {
    if (!this.ctx) {
      this.ctx =
        this.opts.audioContextFactory?.() ?? new AudioContext({ sampleRate: DOWNLINK_SAMPLE_RATE });
    }
    return this.ctx;
  }

  /** Call from a user gesture (for example the Start click) so the browser allows playback. */
  async unlock(): Promise<void> {
    const ctx = this.context();
    if (ctx.state === "suspended") await ctx.resume();
  }

  async playChunk(base64Pcm: string): Promise<void> {
    const samples = base64ToFloat32(base64Pcm);
    if (samples.length === 0) return;
    const generation = this.generation;
    await this.unlock();
    if (generation !== this.generation) return;
    const ctx = this.context();

    const buffer = ctx.createBuffer(1, samples.length, DOWNLINK_SAMPLE_RATE);
    buffer.getChannelData(0).set(samples);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => this.active.delete(source);
    this.active.add(source);

    // After an underrun the old schedule is in the past: restart from "now".
    const startAt = Math.max(this.nextPlayTime, ctx.currentTime);
    source.start(startAt);
    this.nextPlayTime = startAt + buffer.duration;
  }

  /** Silences everything already scheduled and resets the queue. The player stays usable. */
  stopAll(): void {
    this.generation++;
    for (const source of this.active) {
      try {
        source.stop();
      } catch {
        // already ended
      }
    }
    this.active.clear();
    this.nextPlayTime = 0;
  }
}
