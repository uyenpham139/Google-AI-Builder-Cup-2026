/**
 * Echo Guard - Institutional Treasury Content Script
 * Injected into http://localhost:3000/* to provide instant browser-level
 * Zero-Trust synchronization with the Google Meet session.
 */

(function () {
  console.log('[Echo Guard] Treasury Zero-Trust Interlock Active.');

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'ECHO_STATUS_UPDATE') {
      applyStatus(message.status);
      sendResponse({ acknowledged: true });
    }
  });
  chrome.runtime.sendMessage({ type: 'GET_STATUS' }).then(applyStatus).catch(() => {});

  function applyStatus(status) {
    if (status.treasuryBannerEnabled === false) { removeFreezeBanner(); return; }
    // A disconnected call or dismissed alert cannot establish that the bank
    // unlocked. Preserve the last banner until the ERP channel confirms release.
    if (status.treasuryConnectionStatus !== 'connected') return;
    if (status.treasuryLocked === true) showFreezeBanner(status.treasuryReason);
    else if (status.treasuryLocked === false) removeFreezeBanner();
  }

  function showFreezeBanner(reason) {
    if (document.getElementById('echo-treasury-banner')) return;

    const banner = document.createElement('div');
    banner.id = 'echo-treasury-banner';
    banner.style.cssText = `
      position: fixed;
      top: 12px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 9999999;
      background: #dc2626;
      color: #ffffff;
      padding: 10px 20px;
      border-radius: 9999px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 13px;
      font-weight: 600;
      box-shadow: 0 10px 25px -5px rgba(220, 38, 38, 0.6);
      display: flex;
      align-items: center;
      gap: 10px;
      letter-spacing: 0.2px;
      animation: echo-banner-drop 0.3s ease-out;
    `;

    banner.textContent = `ECHO ZERO-TRUST LOCK: ${reason || 'Coercion detected in a monitored call'} · CAEP RFC 9493 · Release after verification in Treasury`;

    document.body.appendChild(banner);
  }

  function removeFreezeBanner() {
    const el = document.getElementById('echo-treasury-banner');
    if (el) el.remove();
  }
})();
