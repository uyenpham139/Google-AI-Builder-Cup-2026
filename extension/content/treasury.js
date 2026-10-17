/**
 * Echo Guard - Institutional Treasury Content Script
 * Injected into http://localhost:3000/* to provide instant browser-level
 * Zero-Trust synchronization with the Google Meet session.
 */

(function () {
  console.log('[Echo Guard] Treasury Zero-Trust Interlock Active.');

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'ECHO_FREEZE_TREASURY') {
      console.warn('[Echo Guard] Received Emergency Freeze signal from Google Meet call!', message);
      showFreezeBanner(message.reason);
      sendResponse({ acknowledged: true });
    } else if (message.type === 'ECHO_UNLOCK_TREASURY') {
      removeFreezeBanner();
      sendResponse({ acknowledged: true });
    }
  });

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

    banner.innerHTML = `
      <span style="font-size: 16px;">🚨</span>
      <span>ECHO ZERO-TRUST LOCK: ${reason || 'Coercion detected in Google Meet'}</span>
      <span style="background: rgba(0,0,0,0.25); padding: 2px 8px; border-radius: 6px; font-size: 11px;">CAEP RFC 9493</span>
    `;

    document.body.appendChild(banner);
  }

  function removeFreezeBanner() {
    const el = document.getElementById('echo-treasury-banner');
    if (el) el.remove();
  }
})();
