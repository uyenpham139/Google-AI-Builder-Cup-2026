/** A reconnecting channel whose callbacks cannot revive a replaced socket. */
export class SocketChannel {
  constructor({ onState = () => {}, onMessage = () => {}, WebSocketClass = WebSocket, timers = globalThis }) {
    this.onState = onState;
    this.onMessage = onMessage;
    this.WebSocketClass = WebSocketClass;
    this.timers = timers;
    this.state = 'disconnected';
    this.socket = null;
    this.pending = [];
  }

  setState(state) {
    this.state = state;
    this.onState(state);
  }

  configure(url, enabled = true) {
    if (this.url === url && this.enabled === enabled) return this.connect();
    this.enabled = enabled;
    this.url = url;
    this.stop();
    if (!enabled) this.pending = [];
    this.connect();
  }

  stop() {
    this.timers.clearTimeout(this.retry);
    this.timers.clearInterval(this.heartbeat);
    this.retry = this.heartbeat = null;
    const previous = this.socket;
    this.socket = null;
    previous?.close();
    this.setState('disconnected');
  }

  scheduleReconnect() {
    if (!this.enabled || this.retry) return;
    this.retry = this.timers.setTimeout(() => {
      this.retry = null;
      this.connect();
    }, 3000);
  }

  connect() {
    if (!this.enabled || (this.socket && this.socket.readyState < 2)) return;
    this.timers.clearTimeout(this.retry);
    this.retry = null;
    this.setState('connecting');
    try {
      const socket = new this.WebSocketClass(this.url);
      this.socket = socket;
      socket.onopen = () => {
        if (this.socket !== socket) return;
        this.setState('connected');
        // Chrome 116+: traffic within 30 seconds keeps an active MV3 socket alive.
        this.heartbeat = this.timers.setInterval(() => {
          if (this.socket === socket && socket.readyState === 1) socket.send(JSON.stringify({ type: 'ping' }));
        }, 20000);
        while (this.pending.length && socket.readyState === 1) this.send(this.pending.shift(), true);
      };
      socket.onmessage = event => {
        if (this.socket !== socket) return;
        try {
          Promise.resolve(this.onMessage(JSON.parse(event.data))).catch(() => console.warn('[Echo] Message processing failed'));
        } catch {
          console.warn('[Echo] Ignoring an invalid backend message');
        }
      };
      socket.onerror = () => {
        if (this.socket === socket) this.setState('error');
      };
      socket.onclose = () => {
        if (this.socket !== socket) return;
        this.socket = null;
        this.timers.clearInterval(this.heartbeat);
        this.heartbeat = null;
        this.setState('disconnected');
        this.scheduleReconnect();
      };
    } catch {
      this.socket = null;
      this.setState('error');
      this.scheduleReconnect();
    }
  }

  send(message, queue = false) {
    if (!this.enabled) return false;
    if (this.socket?.readyState === 1) {
      try {
        this.socket.send(JSON.stringify(message));
        return true;
      } catch {
        this.stop();
        this.scheduleReconnect();
      }
    }
    if (queue) {
      this.pending.push(message);
      if (this.pending.length > 30) this.pending.shift();
      this.connect();
    }
    return false;
  }
}
