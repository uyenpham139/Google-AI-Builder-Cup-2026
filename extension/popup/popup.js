/**
 * Echo Guard - Popup Controller
 */

document.addEventListener('DOMContentLoaded', async () => {
  const connectionPill = document.getElementById('connection-pill');
  const connectionText = document.getElementById('connection-text');
  const threatLabel = document.getElementById('threat-label');
  const riskMeterFill = document.getElementById('risk-meter-fill');
  const riskScoreDisplay = document.getElementById('risk-score-display');
  const caepStatus = document.getElementById('caep-status');
  const meetStatusText = document.getElementById('meet-status-text');
  const meetDetailText = document.getElementById('meet-detail-text');

  const btnSimAttack = document.getElementById('btn-sim-attack');
  const btnSimNormal = document.getElementById('btn-sim-normal');
  const btnResetAlert = document.getElementById('btn-reset-alert');

  const toggleSettings = document.getElementById('toggle-settings');
  const settingsDrawer = document.getElementById('settings-drawer');
  const wsUrlInput = document.getElementById('ws-url-input');
  const btnSaveSettings = document.getElementById('btn-save-settings');

  // Load initial settings
  const stored = await chrome.storage.local.get(['echoConfig']);
  if (stored.echoConfig && stored.echoConfig.wsUrl) {
    wsUrlInput.value = stored.echoConfig.wsUrl;
  }

  // Check active Google Meet tabs
  checkMeetTabs();

  // Query background status
  fetchStatus();

  // Polling fallback
  const pollInterval = setInterval(fetchStatus, 1500);
  window.addEventListener('unload', () => clearInterval(pollInterval));

  // Listen for real-time broadcasts
  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'ECHO_STATUS_UPDATE' && message.status) {
      applyStatus(message.status);
    }
  });

  function checkMeetTabs() {
    chrome.tabs.query({ url: '*://meet.google.com/*' }, (tabs) => {
      if (tabs && tabs.length > 0) {
        meetStatusText.textContent = `Google Meet Active (${tabs.length} tab${tabs.length > 1 ? 's' : ''})`;
        meetDetailText.textContent = 'Echo Guard HUD is actively monitoring dialogue';
        meetStatusText.style.color = '#34d399';
      } else {
        meetStatusText.textContent = 'Google Meet Standby';
        meetDetailText.textContent = 'HUD automatically injects when you join a call';
        meetStatusText.style.color = '#e2e8f0';
      }
    });
  }

  function fetchStatus() {
    chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (res) => {
      if (chrome.runtime.lastError || !res) return;
      applyStatus(res);
    });
  }

  function applyStatus(status) {
    // 1. Connection pill
    connectionPill.className = 'header-status ' + (status.connectionStatus || 'disconnected');
    if (status.connectionStatus === 'connected') {
      connectionText.textContent = 'Engine Online';
    } else if (status.connectionStatus === 'connecting') {
      connectionText.textContent = 'Connecting...';
    } else {
      connectionText.textContent = 'Offline';
    }

    // 2. Risk Meter & Assessment
    const score = status.currentRiskScore || 0;
    const pct = Math.round(score * 100);
    riskScoreDisplay.textContent = `${pct}%`;
    riskMeterFill.style.width = `${Math.max(5, pct)}%`;

    if (score >= 0.85 || (status.lastAlert && status.lastAlert.action === 'TRIGGER_BARGE_IN_AND_LOCK')) {
      threatLabel.textContent = 'CRITICAL FRAUD';
      threatLabel.style.color = '#ef4444';
      riskMeterFill.style.background = '#ef4444';
      caepStatus.textContent = '🔒 TREASURY FROZEN (RFC 9493)';
      caepStatus.style.color = '#f87171';
      caepStatus.style.background = 'rgba(239, 68, 68, 0.2)';
    } else if (score >= 0.6) {
      threatLabel.textContent = 'SUSPICIOUS';
      threatLabel.style.color = '#f59e0b';
      riskMeterFill.style.background = '#f59e0b';
      caepStatus.textContent = 'ELEVATED MONITORING';
      caepStatus.style.color = '#fbbf24';
      caepStatus.style.background = 'rgba(245, 158, 11, 0.2)';
    } else {
      threatLabel.textContent = 'SAFE';
      threatLabel.style.color = '#10b981';
      riskMeterFill.style.background = '#10b981';
      caepStatus.textContent = 'CAEP RFC 9493 ARMED';
      caepStatus.style.color = '#38bdf8';
      caepStatus.style.background = 'rgba(56, 189, 248, 0.1)';
    }
  }

  // Button actions
  btnSimAttack.addEventListener('click', () => {
    btnSimAttack.style.opacity = '0.5';
    chrome.runtime.sendMessage({ type: 'SIMULATE_CEO_ATTACK' }, () => {
      setTimeout(() => {
        btnSimAttack.style.opacity = '1';
        fetchStatus();
      }, 500);
    });
  });

  btnSimNormal.addEventListener('click', () => {
    btnSimNormal.style.opacity = '0.5';
    chrome.runtime.sendMessage({ type: 'SIMULATE_NORMAL_CALL' }, () => {
      setTimeout(() => {
        btnSimNormal.style.opacity = '1';
        fetchStatus();
      }, 500);
    });
  });

  btnResetAlert.addEventListener('click', () => {
    chrome.runtime.sendMessage({
      type: 'DISMISS_ALERT',
      reason: 'Operator cleared alert from popup',
    }, () => {
      fetchStatus();
    });
  });

  toggleSettings.addEventListener('click', () => {
    const isHidden = settingsDrawer.style.display === 'none';
    settingsDrawer.style.display = isHidden ? 'flex' : 'none';
  });

  btnSaveSettings.addEventListener('click', async () => {
    const newWsUrl = wsUrlInput.value.trim();
    if (!newWsUrl) return;

    const stored = await chrome.storage.local.get(['echoConfig']);
    const updated = { ...(stored.echoConfig || {}), wsUrl: newWsUrl };

    chrome.runtime.sendMessage({
      type: 'UPDATE_CONFIG',
      config: updated,
    }, () => {
      settingsDrawer.style.display = 'none';
      fetchStatus();
    });
  });
});
