import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
import { SocketChannel } from '../background/socket_channel.mjs';

const source = (await readFile(new URL('../background/service_worker.js', import.meta.url), 'utf8')).replace(/^import .*;\r?\n/m, '');
const flush = () => new Promise(resolve => setImmediate(resolve));

async function worker({ restored = {}, bankLocked = false, open = true, savedConfig = {} } = {}) {
  const sockets = [], deliveries = [], actions = [];
  let listener;
  let alarmListener;
  const tabs = [
    { id: 1, url: 'https://meet.google.com/test' },
    { id: 2, url: 'http://localhost:3001/' },
    { id: 3, url: 'http://127.0.0.1:3001/' },
    { id: 4, url: 'http://localhost:3000/transfer' },
  ];
  class FakeSocket {
    constructor(url) {
      if (!['ws:', 'wss:'].includes(new URL(url).protocol)) throw new Error('Invalid WebSocket URL');
      this.url = url; this.readyState = 0; this.sent = []; sockets.push(this);
      if (open) queueMicrotask(() => this.open());
    }
    open() {
      this.readyState = 1; this.onopen?.();
      if (this.url.includes('/api/erp/ws/')) this.receive({ type: 'SYNC_STATUS', isLocked: bankLocked });
    }
    close() { this.readyState = 3; this.onclose?.(); }
    send(raw) { this.sent.push(JSON.parse(raw)); }
    receive(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
  }
  const timers = { setTimeout: () => 1, setInterval: () => 2, clearTimeout() {}, clearInterval() {} };
  const noopEvent = { addListener() {} };
  const session = { echoRuntime: restored };
  const chrome = {
    runtime: { onMessage: { addListener(fn) { listener = fn; } }, onInstalled: noopEvent, onStartup: noopEvent, sendMessage: async () => {} },
    alarms: { get: async () => ({}), create() {}, onAlarm: { addListener(fn) { alarmListener = fn; } } },
    storage: {
      local: { get: async () => ({ echoConfig: savedConfig }), set: async () => {} },
      session: { get: async () => structuredClone(session), set: async value => Object.assign(session, structuredClone(value)) },
    },
    action: { setBadgeText() {}, setBadgeBackgroundColor() {} },
    notifications: { create: async () => {} },
    tabs: {
      query: async ({ url }) => tabs.filter(tab => url.some(pattern => tab.url.startsWith(pattern.slice(0, -1)))),
      sendMessage: async (id, message) => deliveries.push({ id, message: structuredClone(message) }),
      update: async (id, change) => actions.push({ id, change: structuredClone(change) }), create: async change => actions.push({ change: structuredClone(change) }),
    },
  };
  class TestChannel extends SocketChannel { constructor(options) { super({ ...options, timers, WebSocketClass: FakeSocket }); } }
  vm.runInNewContext(source, { chrome, SocketChannel: TestChannel, URL, console });
  const request = message => new Promise(resolve => listener(message, {}, result => resolve(structuredClone(result))));
  await request({ type: 'GET_STATUS' }); await flush();
  return { request, sockets, deliveries, actions, session, alarm: () => alarmListener({ name: 'echo-connection-check' }) };
}

const alert = { type: 'SECURITY_ALERT', risk_score: 0.95, action: 'TRIGGER_BARGE_IN_AND_LOCK', session_id: 'call-1' };

test('worker activation reconnects both channels and restores an existing alert', async () => {
  const w = await worker({ bankLocked: true, restored: { lastAlert: alert, currentRiskScore: 0.95 } });
  const status = await w.request({ type: 'GET_STATUS' });
  assert.equal(status.connectionStatus, 'connected');
  assert.equal(status.treasuryConnectionStatus, 'connected');
  assert.equal(status.treasuryLocked, true); assert.equal(status.lastAlert.session_id, 'call-1');
  assert.equal(w.sockets.length, 2);
});

test('critical alerts reach both Meet and localhost call tabs', async () => {
  const w = await worker(); w.sockets[0].receive(alert); await flush();
  const targets = w.deliveries.filter(d => d.message.type === 'ECHO_SECURITY_ALERT').map(d => d.id);
  assert.deepEqual(targets.sort(), [1, 2, 3]);
});

test('dismissing a call waits for acknowledgement and never reports an unlocked bank', async () => {
  const w = await worker({ bankLocked: true });
  w.sockets[0].receive(alert); await flush();
  assert.equal((await w.request({ type: 'DISMISS_ALERT' })).success, true);
  assert((await w.request({ type: 'GET_STATUS' })).lastAlert);
  w.sockets[0].receive({ type: 'ALERT_DISMISSED' }); await flush();
  const status = await w.request({ type: 'GET_STATUS' });
  assert.equal(status.lastAlert, null); assert.equal(status.treasuryLocked, true);
  assert(!w.deliveries.some(d => d.message.type === 'ECHO_UNLOCK_TREASURY'));
});

test('review opens the existing treasury tab and only the ERP release clears the lock', async () => {
  const w = await worker({ bankLocked: true });
  w.sockets[0].receive(alert); await flush();
  await w.request({ type: 'OPEN_TREASURY' });
  assert.deepEqual(w.actions, [{ id: 4, change: { active: true } }]);
  assert.equal((await w.request({ type: 'GET_STATUS' })).treasuryLocked, true);
  assert(w.sockets.every(socket => socket.sent.every(message => !message.type.includes('unlock'))));
  w.sockets[1].receive({ type: 'UNLOCK_SESSION' }); await flush();
  const released = await w.request({ type: 'GET_STATUS' });
  assert.equal(released.treasuryLocked, false); assert.equal(released.lastAlert, null);
});

test('captions that wake a disconnected worker are queued rather than lost', async () => {
  const w = await worker({ open: false });
  await w.request({ type: 'TRANSCRIPT_TURN', text: 'first new caption' });
  assert.equal(w.sockets[0].sent.length, 0);
  w.sockets[0].open();
  assert.equal(w.sockets[0].sent[0].text, 'first new caption');
});

test('an authoritative unlocked sync clears an alert restored after an offline release', async () => {
  const w = await worker({ bankLocked: false, restored: { lastAlert: alert, currentRiskScore: 0.95 } });
  assert.equal((await w.request({ type: 'GET_STATUS' })).lastAlert, null);
});

test('treasury reconnect reconciles an operator release that happened while the bank channel was offline', async () => {
  const w = await worker({ bankLocked: true });
  w.sockets[0].receive(alert); await flush();
  w.sockets[1].receive({ type: 'SYNC_STATUS', isLocked: false }); await flush();
  const status = await w.request({ type: 'GET_STATUS' });
  assert.equal(status.lastAlert, null); assert.equal(status.treasuryLocked, false);
});

test('the recovery alarm reconnects a closed channel without replacing the healthy bank connection', async () => {
  const w = await worker(); w.sockets[0].close();
  w.alarm(); await flush();
  assert.equal(w.sockets.length, 3);
  assert.equal(w.sockets[1].readyState, 1);
  assert.equal((await w.request({ type: 'GET_STATUS' })).connectionStatus, 'connected');
});

test('invalid saved settings leave the popup usable for correction', async () => {
  const w = await worker({ savedConfig: { wsUrl: 'invalid endpoint' } });
  assert.equal((await w.request({ type: 'GET_STATUS' })).connectionStatus, 'error');
  assert.equal((await w.request({ type: 'UPDATE_CONFIG', config: { wsUrl: 'ws://engine/ws/call' } })).success, true);
  await flush();
  assert.equal((await w.request({ type: 'GET_STATUS' })).connectionStatus, 'connected');
});
