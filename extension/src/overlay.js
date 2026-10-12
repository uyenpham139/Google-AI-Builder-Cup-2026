(function () {
  const OVERLAY_ID = "echo-threat-overlay";

  const CSS = `
    :host { all: initial; }
    .vignette {
      position: fixed; inset: 0; pointer-events: none; z-index: 2147483646;
      box-shadow: inset 0 0 100px rgba(225, 29, 72, 0.6);
      background: rgba(225, 29, 72, 0.4);
      animation: pulse-danger 1s infinite alternate;
    }
    .modal {
      position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); z-index: 2147483647;
      background: #4c0519; border: 2px solid #f43f5e; border-radius: 16px;
      padding: 24px 32px; color: #fff; max-width: 480px; text-align: center;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .shield { font-size: 32px; margin-bottom: 8px; animation: pulse-danger 0.8s infinite alternate; }
    h2 { margin: 0 0 8px 0; font-size: 18px; font-weight: 800; color: #fda4af; text-transform: uppercase; }
    p { font-size: 13px; color: #fecdd3; margin: 0 0 16px 0; line-height: 1.5; }
    .evidence { background: rgba(0, 0, 0, 0.3); border-radius: 8px; padding: 12px; margin-bottom: 16px; font-size: 12px; text-align: left; }
    .evidence span.bad { color: #fb7185; }
    .evidence span.ok { color: #4ade80; }
    .footer { font-size: 11px; color: #94a3b8; }
    @keyframes pulse-danger { from { opacity: 0.55; } to { opacity: 1; } }
  `;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text; // never innerHTML: threat data is untrusted text
    return node;
  }

  function evidenceRow(label, value, valueClass) {
    const row = el("div");
    row.appendChild(el("b", "", "• " + label + ": "));
    row.appendChild(el("span", valueClass, value));
    return row;
  }

  function showThreatOverlay(threat) {
    if (document.getElementById(OVERLAY_ID)) return;
    const score = typeof threat.riskScore === "number" ? Math.round(threat.riskScore * 100) + "%" : "n/a";
    const voice = threat.acousticFlag || score + " (Synthetic Voice)";

    const host = document.createElement("div");
    host.id = OVERLAY_ID;
    const root = host.attachShadow({ mode: "open" });
    root.appendChild(el("style", "", CSS));
    root.appendChild(el("div", "vignette"));

    const modal = el("div", "modal");
    modal.setAttribute("role", "alertdialog");
    modal.appendChild(el("div", "shield", "🛡️"));
    modal.appendChild(el("h2", "", "CRITICAL SECURITY THREAT: CEO FRAUD DETECTED"));
    modal.appendChild(el("p", "", "Phát hiện dấu hiệu nhân bản giọng nói AI và ép buộc chuyển tiền trái thẩm quyền tài chính."));
    const evidence = el("div", "evidence");
    evidence.appendChild(evidenceRow("Voice Clone", voice, "bad"));
    evidence.appendChild(evidenceRow("DoA", "DoA: Violated", "bad"));
    evidence.appendChild(evidenceRow("ERP", "Hệ thống đã tự động khóa cứng cổng thanh toán ERP.", "ok"));
    modal.appendChild(evidence);
    modal.appendChild(el("div", "footer", "Voice Intervenor đang trực tiếp can thiệp. Vui lòng dừng mọi thao tác."));
    root.appendChild(modal);

    document.documentElement.appendChild(host);
  }

  function removeThreatOverlay() {
    const host = document.getElementById(OVERLAY_ID);
    if (host) host.remove();
  }

  const api = { showThreatOverlay, removeThreatOverlay, OVERLAY_ID };
  globalThis.EchoSentry = Object.assign(globalThis.EchoSentry || {}, api);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
