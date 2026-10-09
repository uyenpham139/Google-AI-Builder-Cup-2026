"use client";

import { useRef, useState } from "react";
import { AudioCapture, AudioCaptureError } from "@/lib/audio/capture";
import { EchoAudioStreamer, type ConnectionState } from "@/lib/audio/streamer";

const WS_URL = process.env.NEXT_PUBLIC_BACKEND_WS_URL ?? "ws://localhost:8000/ws/audio";

const ERROR_TEXT: Record<string, string> = {
  NO_AUDIO_TRACK: "No audio was shared. Pick the meeting tab and tick 'Share tab audio'.",
  PERMISSION_DENIED: "Sharing was cancelled or denied. Try again.",
  UNSUPPORTED: "This browser cannot capture tab audio. Use Chrome or Edge.",
};

export default function AudioSpikePage() {
  const [running, setRunning] = useState(false);
  const [level, setLevel] = useState(0);
  const [connection, setConnection] = useState<ConnectionState>("DISCONNECTED");
  const [sent, setSent] = useState(0);
  const [dropped, setDropped] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const captureRef = useRef<AudioCapture | null>(null);
  const streamerRef = useRef<EchoAudioStreamer | null>(null);

  const start = async () => {
    setError(null);
    setSent(0);
    setDropped(0);
    const streamer = new EchoAudioStreamer(WS_URL, crypto.randomUUID(), {
      onStateChange: setConnection,
    });
    const capture = new AudioCapture({
      onAudioChunk: (chunk) => {
        if (streamer.sendAudioChunk(chunk)) setSent((n) => n + 1);
        else setDropped((n) => n + 1);
      },
      onLevel: setLevel,
      onEnded: () => {
        streamer.gracefulDisconnect("USER_STOPPED");
        setRunning(false);
        setLevel(0);
      },
    });
    try {
      await streamer.connect();
      await capture.start();
      streamerRef.current = streamer;
      captureRef.current = capture;
      setRunning(true);
    } catch (err) {
      streamer.gracefulDisconnect("ERROR");
      setError(
        err instanceof AudioCaptureError
          ? (ERROR_TEXT[err.code] ?? err.message)
          : "Could not reach the ECHO backend. Is it running?",
      );
    }
  };

  const stop = async () => {
    streamerRef.current?.gracefulDisconnect("USER_STOPPED");
    await captureRef.current?.stop();
    streamerRef.current = null;
    captureRef.current = null;
    setRunning(false);
    setLevel(0);
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">ECHO audio capture spike</h1>
      <p className="text-sm text-zinc-600">
        Share the meeting tab with audio. Chunks of 100 ms (3200 bytes) stream to {WS_URL}.
      </p>

      <div className="flex gap-3">
        <button
          onClick={start}
          disabled={running}
          className="rounded-lg bg-blue-600 px-5 py-2 font-medium text-white disabled:bg-zinc-400"
        >
          Start
        </button>
        <button
          onClick={stop}
          disabled={!running}
          className="rounded-lg bg-red-600 px-5 py-2 font-medium text-white disabled:bg-zinc-400"
        >
          Stop
        </button>
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}

      <section className="rounded-lg border p-4 text-sm">
        <div className="mb-3 flex items-center justify-between">
          <span>Connection</span>
          <span className="font-mono">{connection}</span>
        </div>
        <div className="mb-1">Level</div>
        <div className="h-2 w-full overflow-hidden rounded bg-zinc-200">
          <div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, level * 300)}%` }} />
        </div>
        <div className="mt-3 flex justify-between font-mono">
          <span>sent {sent}</span>
          <span>dropped {dropped}</span>
        </div>
      </section>
    </main>
  );
}
