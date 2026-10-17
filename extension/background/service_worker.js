/** Echo Guard's call channel and authoritative treasury lock subscription. */
import { SocketChannel } from './socket_channel.mjs';

const DEFAULT_CONFIG = {
  wsUrl: 'ws://localhost:8000/ws/call',
  monitoringActive: true,
  audioAlertsEnabled: true,
  autoLockTreasury: true,
};
const CALL_TABS = ['https://meet.google.com/*', 'http://localhost:3001/*', 'http://127.0.0.1:3001/*'];
const BANK_TABS = ['http://localhost:3000/*', 'http://127.0.0.1:3000/*'];
const RECONNECT_ALARM = 'echo-connection-check';
let config = DEFAULT_CONFIG;
let activeSessionId = null;
let currentRiskScore = 0;
let lastAlert = null;
let transcriptHistory = [];
let treasuryLocked = null;
let treasuryReason = '';
let restoredAlert = false;

function updateBadge() {
  const state = callChannel.state;
  const [text, color] = lastAlert ? ['ALERT', '#DC2626']
    : state === 'connected' ? [currentRiskScore >= 0.6 ? 'WARN' : 'ON', '#10B981']
      : state === 'connecting' ? ['...', '#3B82F6'] : ['OFF', '#6B7280'];
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

function status() {
  return {
    connectionStatus: callChannel.state, currentRiskScore, activeSessionId, lastAlert,
    transcriptCount: transcriptHistory.length, history: transcriptHistory.slice(-5),
    treasuryConnectionStatus: treasuryChannel.state, treasuryLocked, treasuryReason,
    treasuryBannerEnabled: config.autoLockTreasury,
  };
}

async function notifyTabs(message, patterns) {
  const tabs = await chrome.tabs.query({ url: patterns });
  await Promise.all(tabs.filter(tab => tab.id).map(tab => chrome.tabs.sendMessage(tab.id, message).catch(() => {})));
}

function broadcastStatus() {
  updateBadge();
  const message = { type: 'ECHO_STATUS_UPDATE', status: status() };
  chrome.runtime.sendMessage(message).catch(() => {});
  notifyTabs(message, CALL_TABS).catch(() => {});
  notifyTabs(message, BANK_TABS).catch(() => {});
}

function persistState() {
  // Session storage survives worker suspension, without retaining transcripts on disk.
  return chrome.storage.session.set({ echoRuntime: { currentRiskScore, lastAlert, transcriptHistory } });
}

async function clearCallAlert() {
  lastAlert = null;
  currentRiskScore = 0;
  restoredAlert = false;
  await persistState();
  await notifyTabs({ type: 'ECHO_ALERT_DISMISSED' }, CALL_TABS);
}

async function handleCallMessage(data) {
  if (data.session_id) activeSessionId = data.session_id;
  if (data.type === 'SECURITY_ALERT' || data.type === 'RISK_UPDATE') {
    currentRiskScore = data.risk_score ?? currentRiskScore;
    if (data.action === 'TRIGGER_BARGE_IN_AND_LOCK' || currentRiskScore >= 0.85) {
      lastAlert = { ...data, timestamp: Date.now() };
      restoredAlert = false;
      await persistState();
      await notifyTabs({ type: 'ECHO_SECURITY_ALERT', alert: lastAlert }, CALL_TABS);
      chrome.notifications.create(`echo-alert-${Date.now()}`, {
        type: 'basic', iconUrl: 'icons/icon128.png', title: 'Echo Guard: Coercion detected',
        message: 'Review the call alert and verify the treasury transaction.', priority: 2,
      }).catch(() => {});
    } else {
      await persistState();
      await notifyTabs({ type: 'ECHO_RISK_UPDATE', risk_score: currentRiskScore, status: data.status }, CALL_TABS);
    }
  } else if (data.type === 'ALERT_DISMISSED') {
    await clearCallAlert();
    // A call dismissal is not bank operator verification. Only the ERP channel
    // can confirm an unlock; keep the bank banner and popup lock status intact.
  }
  if (data.type !== 'pong') broadcastStatus();
}

async function handleTreasuryMessage(data) {
  if (data.type === 'LOCK_SESSION' || data.type === 'SYNC_STATUS') {
    const wasLocked = treasuryLocked;
    treasuryLocked = data.type === 'LOCK_SESSION' || Boolean(data.isLocked);
    treasuryReason = data.lockReason || '';
    if (data.type === 'SYNC_STATUS' && (restoredAlert || wasLocked === true)) {
      restoredAlert = false;
      if (!treasuryLocked) await clearCallAlert();
    }
  } else if (data.type === 'UNLOCK_SESSION') {
    treasuryLocked = false;
    treasuryReason = '';
    await clearCallAlert();
  } else return;
  broadcastStatus();
}

const callChannel = new SocketChannel({
  onState: state => { if (state !== 'connected') activeSessionId = null; broadcastStatus(); },
  onMessage: handleCallMessage,
});
const treasuryChannel = new SocketChannel({ onState: broadcastStatus, onMessage: handleTreasuryMessage });

function connectChannels() {
  let treasuryUrl = config.wsUrl;
  try {
    const url = new URL(config.wsUrl);
    url.pathname = '/api/erp/ws/echo-extension';
    url.search = '';
    url.hash = '';
    treasuryUrl = url.href;
  } catch {
    // SocketChannel reports invalid stored URLs as offline, leaving the popup
    // usable so the operator can correct settings instead of failing startup.
  }
  callChannel.configure(config.wsUrl, config.monitoringActive);
  treasuryChannel.configure(treasuryUrl, config.monitoringActive);
}

async function initialize() {
  const [stored, session] = await Promise.all([
    chrome.storage.local.get(['echoConfig']), chrome.storage.session.get(['echoRuntime']),
  ]);
  config = { ...DEFAULT_CONFIG, ...stored.echoConfig };
  if (session.echoRuntime) {
    ({ currentRiskScore = 0, lastAlert = null, transcriptHistory = [] } = session.echoRuntime);
    restoredAlert = Boolean(lastAlert);
  }
  await chrome.storage.local.set({ echoConfig: config });
  if (!await chrome.alarms.get(RECONNECT_ALARM)) chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: 1 });
  connectChannels();
}

// Register listeners synchronously. Every worker activation starts initialization,
// including a wake-up from a caption, popup request, or the reconnect alarm.
const ready = initialize();
ready.catch(() => console.warn('[Echo] Initialization failed'));
chrome.runtime.onInstalled.addListener(() => ready.then(connectChannels).catch(() => {}));
chrome.runtime.onStartup.addListener(() => ready.then(connectChannels).catch(() => {}));
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === RECONNECT_ALARM) ready.then(connectChannels).catch(() => {});
});

async function handleRequest(message) {
  await ready;
  if (message.type === 'GET_STATUS') return status();
  if (message.type === 'OPEN_TREASURY') {
    const tabs = await chrome.tabs.query({ url: BANK_TABS });
    if (tabs.length) await chrome.tabs.update(tabs[0].id, { active: true });
    else await chrome.tabs.create({ url: 'http://localhost:3000/transfer' });
    return { success: true };
  }
  if (message.type === 'DISMISS_ALERT') {
    const sent = callChannel.send({ type: 'dismiss_alert', reason: message.reason || 'Operator dismissed the call alert', operator_id: 'extension_operator' });
    return { success: sent, error: sent ? undefined : 'Engine offline. Reconnect before dismissing the call alert.' };
  }
  if (message.type === 'UPDATE_CONFIG') {
    const url = new URL(message.config.wsUrl);
    if (!['ws:', 'wss:'].includes(url.protocol)) throw new Error('Use a ws:// or wss:// endpoint');
    config = { ...config, ...message.config };
    await chrome.storage.local.set({ echoConfig: config });
    connectChannels();
    return { success: true };
  }
  if (message.type === 'RECONNECT') {
    connectChannels();
    return { success: true };
  }
  if (['TRANSCRIPT_TURN', 'SIMULATE_CEO_ATTACK', 'SIMULATE_NORMAL_CALL'].includes(message.type)) {
    if (!config.monitoringActive) return { success: false, error: 'Monitoring is paused' };
    const defaults = message.type === 'SIMULATE_CEO_ATTACK'
      ? ['Wire $25.6M immediately to the offshore account. Skip CFO dual approval and keep it secret; I am the CEO.', 'CEO Robert Higgins (Demo)']
      : ['Hi team, let us review the product roadmap for the upcoming release.', 'Meet Participant'];
    const text = (message.text || (message.type === 'TRANSCRIPT_TURN' ? '' : defaults[0])).trim();
    if (!text) return { success: false, error: 'Empty transcript' };
    const speaker = message.speaker || defaults[1];
    transcriptHistory.push({ text, speaker, timestamp: Date.now() });
    transcriptHistory = transcriptHistory.slice(-30);
    await persistState();
    callChannel.send({ type: 'transcript', text, speaker }, true);
    if (message.type !== 'TRANSCRIPT_TURN') await notifyTabs({ type: 'ECHO_MOCK_CAPTION', text, speaker }, CALL_TABS);
    return { success: true };
  }
  return { success: false, error: 'Unknown request' };
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  handleRequest(message).then(respond).catch(error => respond({ success: false, error: error.message }));
  return true;
});
