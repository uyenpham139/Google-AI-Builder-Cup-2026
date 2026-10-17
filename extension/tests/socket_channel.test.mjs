import test from 'node:test';
import assert from 'node:assert/strict';
import { SocketChannel } from '../background/socket_channel.mjs';

export function fixture() {
  const sockets = [];
  const jobs = new Map();
  let id = 0;
  const timers = {
    setTimeout(fn, ms) { jobs.set(++id, { fn, ms }); return id; },
    setInterval(fn, ms) { jobs.set(++id, { fn, ms }); return id; },
    clearTimeout(id) { jobs.delete(id); }, clearInterval(id) { jobs.delete(id); },
  };
  class FakeSocket {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    open() { this.readyState = 1; this.onopen?.(); }
    close() { this.readyState = 3; this.onclose?.(); }
    send(raw) { this.sent.push(JSON.parse(raw)); }
    receive(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
  }
  const channel = new SocketChannel({ WebSocketClass: FakeSocket, timers });
  return { channel, sockets, jobs, timers, FakeSocket };
}

test('a caption queued during reconnect is sent once the connection opens', () => {
  const { channel, sockets } = fixture();
  channel.configure('ws://engine/ws/call');
  channel.send({ type: 'transcript', text: 'first waking caption' }, true);
  assert.equal(sockets[0].sent.length, 0);
  sockets[0].open();
  assert.deepEqual(sockets[0].sent, [{ type: 'transcript', text: 'first waking caption' }]);
  assert.equal(channel.pending.length, 0);
});

test('heartbeat traffic runs every 20 seconds and stops when disconnected', () => {
  const { channel, sockets, jobs } = fixture();
  channel.configure('ws://engine/ws/call'); sockets[0].open();
  const heartbeat = [...jobs.values()].find(job => job.ms === 20000);
  assert(heartbeat); heartbeat.fn();
  assert.deepEqual(sockets[0].sent, [{ type: 'ping' }]);
  sockets[0].close();
  assert(![...jobs.values()].some(job => job.ms === 20000));
  [...jobs.values()].find(job => job.ms === 3000).fn();
  assert.equal(sockets.length, 2);
});

test('callbacks from a replaced socket cannot erase the new connection or deliver old messages', () => {
  const { channel, sockets } = fixture();
  const messages = []; channel.onMessage = data => messages.push(data);
  channel.configure('ws://first/ws/call'); const old = sockets[0]; old.open();
  channel.configure('ws://second/ws/call'); const current = sockets[1]; current.open();
  old.onclose(); old.onopen(); old.receive({ type: 'stale' });
  assert.equal(channel.socket, current);
  assert.equal(channel.state, 'connected'); assert.deepEqual(messages, []);
});

test('pausing monitoring clears pending transcripts and disables recovery', () => {
  const { channel, sockets, jobs } = fixture();
  channel.configure('ws://engine/ws/call');
  channel.send({ text: 'queued' }, true);
  channel.configure('ws://engine/ws/call', false);
  channel.send({ text: 'must not retain while paused' }, true);
  channel.connect();
  assert.equal(sockets.length, 1); assert.equal(jobs.size, 0);
  assert.deepEqual(channel.pending, []); assert.equal(channel.state, 'disconnected');
});

test('a disconnected queue is bounded to the latest 30 captions', () => {
  const { channel, sockets } = fixture(); channel.configure('ws://engine/ws/call');
  for (let index = 0; index < 35; index++) channel.send({ index }, true);
  sockets[0].open();
  assert.equal(sockets[0].sent.length, 30);
  assert.equal(sockets[0].sent[0].index, 5);
});

test('invalid socket construction schedules recovery rather than leaving connecting stuck', () => {
  const { timers, jobs } = fixture();
  const channel = new SocketChannel({ timers, WebSocketClass: class { constructor() { throw new Error('offline'); } } });
  channel.configure('ws://engine/ws/call');
  assert.equal(channel.state, 'error');
  assert([...jobs.values()].some(job => job.ms === 3000));
});
