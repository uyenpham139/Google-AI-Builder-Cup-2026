export type ConnectionState = "DISCONNECTED" | "CONNECTING" | "CONNECTED" | "RECONNECTING" | "ERROR";

export interface SessionHandshakeMessage {
  type: "INIT_SESSION";
  sessionId: string;
  timestamp: number;
  audioConfig: {
    encoding: "LINEAR16";
    sampleRate: 16000;
    channels: 1;
    chunkDurationMs: 100;
  };
}

export interface StopStreamMessage {
  type: "STOP_STREAM";
  sessionId: string;
  reason: "USER_STOPPED" | "MEETING_ENDED" | "ERROR";
  timestamp: number;
}

export interface StreamerOptions {
  onStateChange?: (state: ConnectionState) => void;
  onBufferWarning?: (bufferedAmount: number) => void;
  webSocketImpl?: typeof WebSocket;
  reconnectDelaysMs?: number[];
}

const MAX_BUFFERED_BYTES = 64 * 1024;
const WS_OPEN = 1;
// Server refused us on purpose (policy, too big, try later): retrying would only repeat it.
const NO_RETRY_CLOSE_CODES = new Set([1008, 1009, 1013]);

export class EchoAudioStreamer {
  private ws: WebSocket | null = null;
  private _state: ConnectionState = "DISCONNECTED";
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  private readonly delays: number[];

  constructor(
    private readonly wsUrl: string,
    private readonly sessionId: string,
    private readonly opts: StreamerOptions = {},
  ) {
    this.delays = opts.reconnectDelaysMs ?? [1000, 2000, 4000];
  }

  get state(): ConnectionState {
    return this._state;
  }

  private setState(next: ConnectionState) {
    if (this._state === next) return;
    this._state = next;
    this.opts.onStateChange?.(next);
  }

  /** Opens the socket. A failure of this first attempt rejects and is not retried. */
  connect(): Promise<void> {
    this.intentionalClose = false;
    this.setState("CONNECTING");
    return this.openSocket();
  }

  private openSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const Impl = this.opts.webSocketImpl ?? WebSocket;
      const ws = new Impl(this.wsUrl);
      ws.binaryType = "arraybuffer"; // audio goes out as raw binary frames, never Base64
      this.ws = ws;
      let opened = false;

      ws.onopen = () => {
        opened = true;
        this.reconnectAttempts = 0;
        this.sendHandshake(ws);
        this.setState("CONNECTED");
        resolve();
      };
      ws.onerror = (err) => {
        if (!opened) reject(err);
      };
      ws.onclose = (event) => {
        if (this.ws !== ws) return;
        this.ws = null;
        if (opened && NO_RETRY_CLOSE_CODES.has(event.code) && !this.intentionalClose) {
          this.setState("ERROR");
        } else if (opened && event.code !== 1000 && !this.intentionalClose) {
          this.scheduleReconnect();
        } else if (opened) {
          this.setState("DISCONNECTED");
        }
      };
    });
  }

  private sendHandshake(ws: WebSocket) {
    const handshake: SessionHandshakeMessage = {
      type: "INIT_SESSION",
      sessionId: this.sessionId,
      timestamp: Date.now(),
      audioConfig: { encoding: "LINEAR16", sampleRate: 16000, channels: 1, chunkDurationMs: 100 },
    };
    ws.send(JSON.stringify(handshake));
  }

  private scheduleReconnect() {
    if (this.intentionalClose) return;
    if (this.reconnectAttempts >= this.delays.length) {
      this.setState("DISCONNECTED");
      return;
    }
    const delay = this.delays[this.reconnectAttempts++];
    this.setState("RECONNECTING");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket().catch(() => this.scheduleReconnect());
    }, delay);
  }

  /** Returns false when the chunk was not sent (not connected, or the network is backed up). */
  sendAudioChunk(chunk: ArrayBuffer): boolean {
    const ws = this.ws;
    if (!ws || ws.readyState !== WS_OPEN) return false;
    if (ws.bufferedAmount > MAX_BUFFERED_BYTES) {
      this.opts.onBufferWarning?.(ws.bufferedAmount);
      return false; // keep the stream real-time: drop instead of queueing latency
    }
    ws.send(chunk);
    return true;
  }

  gracefulDisconnect(reason: StopStreamMessage["reason"] = "USER_STOPPED"): void {
    this.intentionalClose = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      if (ws.readyState === WS_OPEN) {
        const stop: StopStreamMessage = {
          type: "STOP_STREAM",
          sessionId: this.sessionId,
          reason,
          timestamp: Date.now(),
        };
        ws.send(JSON.stringify(stop));
      }
      ws.close(1000, "Normal Closure");
    }
    this.setState("DISCONNECTED");
  }
}

/** Ends the stream cleanly when the user presses Chrome's "Stop sharing". */
export function attachMeetingLifecycle(
  audioTrack: MediaStreamTrack,
  streamer: EchoAudioStreamer,
  onSessionTerminated: () => void,
): void {
  audioTrack.onended = () => {
    streamer.gracefulDisconnect("USER_STOPPED");
    onSessionTerminated();
  };
}
