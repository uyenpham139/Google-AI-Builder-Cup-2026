import {
  Downsampler,
  PcmChunker,
  TARGET_SAMPLE_RATE,
  computeRms,
  convertFloat32ToInt16,
} from "./pcm";

export type AudioCaptureErrorCode = "UNSUPPORTED" | "PERMISSION_DENIED" | "NO_AUDIO_TRACK";

export class AudioCaptureError extends Error {
  constructor(
    public readonly code: AudioCaptureErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "AudioCaptureError";
  }
}

/** Opens the tab picker and returns a stream that holds audio tracks only. */
export async function initDisplayMediaStream(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new AudioCaptureError("UNSUPPORTED", "This browser cannot capture tab audio.");
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: true, // browsers refuse audio capture without a video request
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "NotAllowedError") {
      throw new AudioCaptureError("PERMISSION_DENIED", "Screen sharing was cancelled or denied.");
    }
    throw err;
  }

  if (stream.getAudioTracks().length === 0) {
    stream.getTracks().forEach((t) => t.stop());
    throw new AudioCaptureError(
      "NO_AUDIO_TRACK",
      "No audio was shared. Choose the meeting tab and tick 'Share tab audio'.",
    );
  }
  stream.getVideoTracks().forEach((t) => t.stop());
  return stream;
}

export interface AudioCaptureOptions {
  onAudioChunk: (chunk: ArrayBuffer) => void;
  onLevel?: (rms: number) => void;
  onEnded?: () => void;
  workletUrl?: string;
}

export class AudioCapture {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private mute: GainNode | null = null;
  private stopping = false;

  constructor(private readonly opts: AudioCaptureOptions) {}

  get running(): boolean {
    return this.ctx !== null;
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.stopping = false;
    const stream = await initDisplayMediaStream();
    const track = stream.getAudioTracks()[0];

    let ctx: AudioContext | null = null;
    try {
      // Ask for 16 kHz; if the browser keeps a hardware rate, Downsampler covers it.
      ctx = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      await ctx.audioWorklet.addModule(this.opts.workletUrl ?? "/echo-pcm-processor.js");

      const downsampler = new Downsampler(ctx.sampleRate);
      const chunker = new PcmChunker((chunk) => this.opts.onAudioChunk(chunk));
      const node = new AudioWorkletNode(ctx, "echo-pcm-processor");
      node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        const mono = event.data;
        this.opts.onLevel?.(computeRms(mono));
        chunker.push(convertFloat32ToInt16(downsampler.process(mono)));
      };

      // The worklet only runs while connected to the destination; a zero-gain
      // node keeps it alive without playing the meeting a second time.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      const source = ctx.createMediaStreamSource(new MediaStream([track]));
      source.connect(node);
      node.connect(mute);
      mute.connect(ctx.destination);

      this.stream = stream;
      this.ctx = ctx;
      this.source = source;
      this.node = node;
      this.mute = mute;
      track.onended = () => {
        void this.stop().then(() => this.opts.onEnded?.());
      };
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      await ctx?.close().catch(() => undefined);
      throw err;
    }
  }

  async stop(): Promise<void> {
    if (this.stopping || !this.ctx) return;
    this.stopping = true;
    const { stream, ctx, source, node, mute } = this;
    this.stream = this.ctx = this.source = this.node = this.mute = null;

    if (node) node.port.onmessage = null;
    source?.disconnect();
    node?.disconnect();
    mute?.disconnect();
    stream?.getTracks().forEach((t) => {
      t.onended = null;
      t.stop();
    });
    await ctx.close();
  }
}
