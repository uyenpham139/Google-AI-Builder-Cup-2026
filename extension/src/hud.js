(function () {
  const BAR_COUNT = 12;
  const BAR_WIDTH = 3;
  const BAR_GAP = 2;
  const MIN_BAR = 2;
  const ACCENT = "#10b981";

  const TEMPLATE = `
    <style>
      :host {
        position: fixed; top: 16px; right: 16px; z-index: 2147483647;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }
      .hud-card {
        display: flex; align-items: center; gap: 12px;
        background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(8px);
        border: 1px solid rgba(51, 65, 85, 0.8); padding: 8px 14px;
        border-radius: 9999px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
        color: #f8fafc;
      }
      .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #64748b; }
      :host([live]) .status-dot { background: ${ACCENT}; box-shadow: 0 0 10px ${ACCENT}; animation: pulse 1.5s infinite; }
      .meta-text { display: flex; flex-direction: column; }
      .title { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #94a3b8; }
      .status { font-size: 12px; font-weight: 600; color: #f1f5f9; }
      canvas { width: 60px; height: 20px; }
      @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } }
    </style>
    <div class="hud-card">
      <div class="status-dot"></div>
      <div class="meta-text">
        <span class="title">ECHO Sentry</span>
        <span class="status" id="status-text">STANDBY</span>
      </div>
      <canvas id="waveform-canvas" width="60" height="20"></canvas>
    </div>
  `;

  class EchoSentryHud extends HTMLElement {
    constructor() {
      super();
      this._analyser = null;
      this._data = null;
      this._raf = 0;
    }

    connectedCallback() {
      if (!this.shadowRoot) {
        this.attachShadow({ mode: "open" }).innerHTML = TEMPLATE;
      }
      if (this._analyser) this._startLoop();
    }

    disconnectedCallback() {
      this._stopLoop();
    }

    get live() {
      return this._analyser !== null;
    }

    attachAnalyser(analyser) {
      analyser.fftSize = 64;
      this._analyser = analyser;
      this._data = new Uint8Array(analyser.frequencyBinCount);
      this.setAttribute("live", "");
      this._setStatus("LIVE MONITORING");
      this._stopLoop();
      if (this.isConnected) this._startLoop();
    }

    detachAnalyser() {
      this._stopLoop();
      this._analyser = null;
      this._data = null;
      this.removeAttribute("live");
      this._setStatus("STANDBY");
    }

    _setStatus(text) {
      const el = this.shadowRoot && this.shadowRoot.getElementById("status-text");
      if (el) el.textContent = text;
    }

    _startLoop() {
      if (this._raf) return;
      const tick = () => {
        this._raf = requestAnimationFrame(tick);
        this._draw();
      };
      this._raf = requestAnimationFrame(tick);
    }

    _stopLoop() {
      if (this._raf) {
        cancelAnimationFrame(this._raf);
        this._raf = 0;
      }
    }

    _draw() {
      const canvas = this.shadowRoot && this.shadowRoot.getElementById("waveform-canvas");
      const ctx = canvas && canvas.getContext("2d");
      if (!ctx || !this._analyser) return;
      this._analyser.getByteFrequencyData(this._data);

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = ACCENT;
      let x = 1;
      for (let i = 0; i < BAR_COUNT; i++) {
        const level = (this._data[i] || 0) / 255;
        const h = Math.max(MIN_BAR, Math.round(canvas.height * level));
        ctx.fillRect(x, (canvas.height - h) / 2, BAR_WIDTH, h);
        x += BAR_WIDTH + BAR_GAP;
      }
    }
  }

  if (typeof customElements !== "undefined" && !customElements.get("echo-sentry-hud")) {
    customElements.define("echo-sentry-hud", EchoSentryHud);
  }

  const api = { EchoSentryHud, BAR_COUNT };
  globalThis.EchoSentry = Object.assign(globalThis.EchoSentry || {}, api);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
