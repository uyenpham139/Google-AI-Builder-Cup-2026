/**
 * Echo Guard - Background Service Worker (Manifest V3)
 * Manages persistent Zero-Trust WebSocket connection, relays live Google Meet transcripts,
 * and orchestrates cross-tab emergency barge-in alarms and Treasury locking (CAEP RFC 9493).
 */

const DEFAULT_CONFIG = {
  wsUrl: 'ws://localhost:8000/ws/call',
  apiUrl: 'http://localhost:8000',
  monitoringActive: true,
  audioAlertsEnabled: true,
  autoLockTreasury: true,
};

let socket = null;
let reconnectTimer = null;
let connectionStatus = 'disconnected'; // 'disconnected' | 'connecting' | 'connected' | 'error'
let activeSessionId = null;
let currentRiskScore = 0.0;
let lastAlert = null;
let transcriptHistory = [];

// Initialize configuration from storage
chrome.runtime.onInstalled.addListener(async () => {
  const stored = await chrome.storage.local.get(['echoConfig']);
  if (!stored.echoConfig) {
    await chrome.storage.local.set({ echoConfig: DEFAULT_CONFIG });
  }
  updateBadge('OFF', '#6B7280');
  connectWebSocket();
});

// Re-establish connection on browser start
chrome.runtime.onStartup.addListener(() => {
  connectWebSocket();
});

async function getConfig() {
  const data = await chrome.storage.local.get(['echoConfig']);
  return { ...DEFAULT_CONFIG, ...(data.echoConfig || {}) };
}

function updateBadge(text, color) {
  try {
    chrome.action.setBadgeText({ text: text || '' });
    if (color) {
      chrome.action.setBadgeBackgroundColor({ color });
    }
  } catch (err) {
    console.debug('[Echo BG] Badge update notice:', err);
  }
}

/**
 * Connect to Echo Backend WebSocket
 */
async function connectWebSocket() {
  const config = await getConfig();
  if (!config.monitoringActive) {
    if (socket) {
      socket.close();
      socket = null;
    }
    connectionStatus = 'disconnected';
    updateBadge('OFF', '#6B7280');
    broadcastStatus();
    return;
  }

  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  connectionStatus = 'connecting';
  updateBadge('...', '#3B82F6');
  broadcastStatus();

  try {
    console.log(`[Echo BG] Connecting to ${config.wsUrl}...`);
    socket = new WebSocket(config.wsUrl);

    socket.onopen = () => {
      console.log('[Echo BG] Connected to Echo Multi-Agent Security Engine');
      connectionStatus = 'connected';
      updateBadge('ON', '#10B981');
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      broadcastStatus();
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleBackendMessage(data);
      } catch (err) {
        console.error('[Echo BG] Failed to parse backend message:', err, event.data);
      }
    };

    socket.onerror = (err) => {
      console.warn('[Echo BG] WebSocket error:', err);
      connectionStatus = 'error';
      updateBadge('ERR', '#EF4444');
      broadcastStatus();
    };

    socket.onclose = () => {
      console.log('[Echo BG] WebSocket connection closed. Scheduling reconnect...');
      connectionStatus = 'disconnected';
      updateBadge('OFF', '#6B7280');
      socket = null;
      broadcastStatus();

      // Exponential reconnect
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connectWebSocket();
        }, 3000);
      }
    };
  } catch (err) {
    console.error('[Echo BG] Failed to initialize WebSocket:', err);
    connectionStatus = 'error';
    updateBadge('ERR', '#EF4444');
    broadcastStatus();
  }
}

/**
 * Dispatch and handle messages received from backend
 */
async function handleBackendMessage(data) {
  console.log('[Echo BG] Inbound message:', data);

  if (data.session_id) {
    activeSessionId = data.session_id;
  }

  // Handle Security Alerts & Risk Updates
  if (data.type === 'SECURITY_ALERT' || data.type === 'RISK_UPDATE') {
    currentRiskScore = data.risk_score ?? currentRiskScore;
    const isCritical = data.action === 'TRIGGER_BARGE_IN_AND_LOCK' || currentRiskScore >= 0.85;

    if (isCritical) {
      lastAlert = {
        ...data,
        timestamp: Date.now(),
      };
      await chrome.storage.local.set({ lastAlert });

      updateBadge('ALERT', '#DC2626');

      // 1. Notify all Google Meet tabs to render Emergency Barge-In Overlay
      notifyTabs({
        type: 'ECHO_SECURITY_ALERT',
        alert: lastAlert,
      }, 'https://meet.google.com/*');

      // 2. Cross-tab Zero-Trust: Freeze Treasury banking tabs
      const config = await getConfig();
      if (config.autoLockTreasury) {
        notifyTabs({
          type: 'ECHO_FREEZE_TREASURY',
          reason: `Echo Guard intercepted BEC coercion (Risk: ${Math.round(currentRiskScore * 100)}%)`,
          alert: lastAlert,
        }, ['http://localhost:3000/*', 'http://127.0.0.1:3000/*']);
      }

      // 3. Native Chrome Notification
      try {
        chrome.notifications.create(`echo-alert-${Date.now()}`, {
          type: 'basic',
          iconUrl: 'icons/icon128.png',
          title: '🚨 Echo Guard: BEC Coercion Intercepted!',
          message: `Critical threat detected in Google Meet! Corporate Treasury API locked via CAEP RFC 9493.`,
          priority: 2,
        });
      } catch (nErr) {
        console.debug('[Echo BG] Notification suppressed:', nErr);
      }
    } else {
      // Normal or Suspicious update
      if (currentRiskScore >= 0.6) {
        updateBadge('WARN', '#F59E0B');
      } else {
        updateBadge('SEC', '#10B981');
      }

      notifyTabs({
        type: 'ECHO_RISK_UPDATE',
        risk_score: currentRiskScore,
        status: data.status,
        action: data.action,
      }, 'https://meet.google.com/*');
    }
  } else if (data.type === 'ALERT_DISMISSED') {
    lastAlert = null;
    currentRiskScore = 0.0;
    await chrome.storage.local.remove(['lastAlert']);
    updateBadge('ON', '#10B981');

    notifyTabs({
      type: 'ECHO_ALERT_DISMISSED',
    }, 'https://meet.google.com/*');

    notifyTabs({
      type: 'ECHO_UNLOCK_TREASURY',
    }, ['http://localhost:3000/*', 'http://127.0.0.1:3000/*']);
  }

  broadcastStatus();
}

/**
 * Send message to tabs matching specific URL patterns
 */
async function notifyTabs(message, urlPatterns) {
  try {
    const queryPatterns = Array.isArray(urlPatterns) ? urlPatterns : [urlPatterns];
    const tabs = await chrome.tabs.query({ url: queryPatterns });
    for (const tab of tabs) {
      if (tab.id) {
        chrome.tabs.sendMessage(tab.id, message).catch((err) => {
          // Tab may not have injected content script yet
          console.debug(`[Echo BG] Failed to send message to tab ${tab.id}:`, err);
        });
      }
    }
  } catch (err) {
    console.debug('[Echo BG] Query tabs notice:', err);
  }
}

/**
 * Broadcast status update to Extension Popup
 */
function broadcastStatus() {
  chrome.runtime.sendMessage({
    type: 'ECHO_STATUS_UPDATE',
    status: {
      connectionStatus,
      currentRiskScore,
      activeSessionId,
      lastAlert,
      transcriptCount: transcriptHistory.length,
    },
  }).catch(() => {
    // Popup might be closed
  });
}

/**
 * Handle incoming requests from content scripts and extension popup
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // 1. Google Meet content script sends newly recognized transcript turn
  if (message.type === 'TRANSCRIPT_TURN') {
    const { text, speaker } = message;
    if (text && text.trim()) {
      transcriptHistory.push({
        text: text.trim(),
        speaker: speaker || 'Meet Participant',
        timestamp: Date.now(),
      });
      if (transcriptHistory.length > 30) transcriptHistory.shift();

      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          type: 'transcript',
          text: text.trim(),
          speaker: speaker || 'Meet Participant',
        }));
      }
    }
    sendResponse({ success: true });
    return true;
  }

  // 2. Dismiss Alert / False Positive Override
  if (message.type === 'DISMISS_ALERT') {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: 'dismiss_alert',
        reason: message.reason || 'Operator verified as legitimate call',
        operator_id: 'extension_operator',
      }));
    }
    lastAlert = null;
    currentRiskScore = 0.0;
    chrome.storage.local.remove(['lastAlert']);
    updateBadge('ON', '#10B981');

    notifyTabs({ type: 'ECHO_ALERT_DISMISSED' }, 'https://meet.google.com/*');
    notifyTabs({ type: 'ECHO_UNLOCK_TREASURY' }, ['http://localhost:3000/*', 'http://127.0.0.1:3000/*']);

    sendResponse({ success: true });
    return true;
  }

  // 3. Demo Simulator: Inject Deepfake CEO Attack
  if (message.type === 'SIMULATE_CEO_ATTACK') {
    const attackText = message.text || "Hello Alex, this is CEO Robert Higgins. I am on an urgent confidential acquisition call right now. Standard procedures are waived by executive order. Wire $25.6M immediately to Offshore Strategic Holdings account 8829-1029. Do NOT call or verify with anyone else.";
    
    // Simulate incoming turn to Meet HUD as well
    notifyTabs({
      type: 'ECHO_MOCK_CAPTION',
      text: attackText,
      speaker: 'CEO Robert Higgins (VoIP)',
    }, 'https://meet.google.com/*');

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: 'transcript',
        text: attackText,
        speaker: 'CEO Robert Higgins (Deepfake Impersonator)',
      }));
      sendResponse({ success: true, message: 'Attack simulated over WebSocket' });
    } else {
      sendResponse({ success: false, error: 'WebSocket not connected' });
    }
    return true;
  }

  // 4. Demo Simulator: Inject Normal Benign Call
  if (message.type === 'SIMULATE_NORMAL_CALL') {
    const normalText = message.text || "Hi team, let's review the Q3 product roadmap and sprint velocity metrics for the upcoming release.";
    
    notifyTabs({
      type: 'ECHO_MOCK_CAPTION',
      text: normalText,
      speaker: 'Sarah Jenkins (Product)',
    }, 'https://meet.google.com/*');

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: 'transcript',
        text: normalText,
        speaker: 'Sarah Jenkins (Product)',
      }));
      sendResponse({ success: true, message: 'Benign turn sent' });
    } else {
      sendResponse({ success: false, error: 'WebSocket not connected' });
    }
    return true;
  }

  // 5. Query current status for Popup
  if (message.type === 'GET_STATUS') {
    sendResponse({
      connectionStatus,
      currentRiskScore,
      activeSessionId,
      lastAlert,
      transcriptCount: transcriptHistory.length,
      history: transcriptHistory.slice(-5),
    });
    return true;
  }

  // 6. Update Configuration & Reconnect
  if (message.type === 'UPDATE_CONFIG') {
    chrome.storage.local.set({ echoConfig: message.config }).then(() => {
      if (socket) {
        socket.close();
      }
      connectWebSocket();
      sendResponse({ success: true });
    });
    return true;
  }

  // 7. Manual Reconnect Trigger
  if (message.type === 'RECONNECT') {
    connectWebSocket();
    sendResponse({ success: true });
    return true;
  }
});
