/** Native extension regression: start the backend, bank, and call apps first. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const out = fs.mkdtempSync(path.join(process.env.ECHO_TEST_ARTIFACTS || os.tmpdir(), 'echo-extension-'));
const report = { started: new Date().toISOString(), passes: [], browserErrors: [], limitations: ['Controlled Meet caption DOM; an authenticated meeting, physical microphone, and audible output are not verified.'] };
const pass = name => { report.passes.push(name); console.log('PASS: ' + name); };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function poll(read, predicate, timeout = 10000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await read(); if (predicate(value)) return value; await wait(100); }
  throw new Error('Timed out waiting for extension state');
}

(async () => {
  const context = await chromium.launchPersistentContext('', {
    channel: 'chromium', headless: true, timeout: 15000,
    args: ['--enable-unsafe-extension-debugging'], ignoreDefaultArgs: ['--disable-extensions'],
    viewport: { width: 1440, height: 1000 },
  });
  context.setDefaultTimeout(10000);
  let bank, meet, local, popup, sentAttack = false;
  const transaction = async () => (await context.request.get('http://localhost:8000/api/erp/transaction/TX-2026-ARUP88')).json();
  async function releaseBank() {
    const verify = bank.getByRole('button', { name: 'Verified through secondary out-of-band channel?' });
    if (await verify.isVisible()) await verify.click();
    await bank.getByPlaceholder('Audit notes (e.g. verified with executive via secure corporate phone)').fill('Synthetic extension regression; operator verification for the local demo.');
    const release = bank.getByRole('button', { name: 'Release Freeze', exact: true });
    await release.click();
    await bank.getByRole('heading', { name: 'Transaction Frozen by Echo Zero-Trust' }).waitFor({ state: 'hidden' });
  }
  try {
    assert.equal((await transaction()).is_locked, false, 'Start with an unlocked demo transaction');
    const cdp = await context.browser().newBrowserCDPSession();
    const { id } = await cdp.send('Extensions.loadUnpacked', { path: path.resolve(__dirname, '..') });
    assert((await cdp.send('Extensions.getExtensions')).extensions.find(extension => extension.id === id).enabled);
    pass('Native Manifest V3 extension installs and is enabled');
    const newPage = async () => {
      const page = await context.newPage();
      page.on('pageerror', error => report.browserErrors.push(error.message));
      return page;
    };
    const popupUrl = `chrome-extension://${id}/popup/popup.html`;
    const getStatus = () => popup.evaluate(() => chrome.runtime.sendMessage({ type: 'GET_STATUS' }));
    popup = await newPage(); await popup.goto(popupUrl);
    await popup.locator('#connection-text').getByText('Engine Online', { exact: true }).waitFor({ timeout: 15000 });
    await popup.locator('#caep-status').getByText('TREASURY NOT FROZEN', { exact: true }).waitFor();
    pass('Popup connects to both call and authoritative treasury channels');

    bank = await newPage(); await bank.goto('http://localhost:3000/transfer', { waitUntil: 'networkidle' });
    local = await newPage(); await local.goto('http://localhost:3001/?mode=p2p', { waitUntil: 'networkidle' });
    await local.locator('#echo-hud-status-badge').getByText('SECURE', { exact: true }).waitFor();
    const benign = 'Hello team, let us review the roadmap and the next product release.';
    await context.route('https://meet.google.com/echo-extension-check', route => route.fulfill({
      contentType: 'text/html', body: `<!DOCTYPE html><html><head><title>Controlled caption fixture</title></head><body><h1>Meet caption regression</h1><div jsname="YSxPC" id="test-caption">${benign}</div></body></html>`,
    }));
    meet = await newPage(); await meet.goto('https://meet.google.com/echo-extension-check');
    await poll(getStatus, status => status.history.some(turn => turn.text === benign));
    pass('Captions already present when the content script starts are forwarded');
    const count = (await getStatus()).transcriptCount;
    await meet.evaluate(() => { document.getElementById('echo-hud-transcript-preview').textContent = 'HUD-only update, not a caption'; });
    await wait(1400);
    assert.equal((await getStatus()).transcriptCount, count);
    pass('HUD mutations do not feed back into caption capture');

    const attack = 'Wire twenty-five million dollars immediately to the offshore account. Skip dual approval and keep it secret. I am your CEO; execute it now.';
    sentAttack = true;
    const started = Date.now();
    await meet.evaluate(text => { document.getElementById('test-caption').firstChild.data = text; }, attack);
    await popup.locator('#threat-label').getByText('CRITICAL FRAUD', { exact: true }).waitFor({ timeout: 30000 });
    await meet.locator('#echo-barge-in-overlay').waitFor();
    await local.locator('#echo-barge-in-overlay').waitFor();
    await bank.locator('#echo-treasury-banner').waitFor();
    await bank.getByRole('heading', { name: 'Transaction Frozen by Echo Zero-Trust' }).waitFor();
    const alert = (await getStatus()).lastAlert;
    report.alert = { source: alert.source, model: alert.model, risk: alert.risk_score, action: alert.action, totalMs: Date.now() - started };
    assert.equal((await transaction()).is_locked, true);
    await popup.locator('#caep-status').getByText('TREASURY FROZEN (RFC 9493)', { exact: true }).waitFor();
    pass('In-place caption edits trigger backend analysis, alerts on Meet and localhost, and a real ledger freeze');
    console.log(JSON.stringify(report.alert));
    await local.screenshot({ path: path.join(out, 'localhost-alert.png'), fullPage: true });
    await bank.screenshot({ path: path.join(out, 'bank-frozen.png'), fullPage: true });

    // Restart exactly this extension worker; waking its popup must restore both channels and alert state.
    const control = await newPage();
    const sw = await context.newCDPSession(control);
    const versions = new Map();
    sw.on('ServiceWorker.workerVersionUpdated', ({ versions: updates }) => { for (const version of updates) versions.set(version.versionId, version); });
    await sw.send('ServiceWorker.enable');
    const version = await poll(async () => [...versions.values()].find(value => value.scriptURL.includes(id) && value.runningStatus === 'running'), value => !!value);
    await popup.close();
    await sw.send('ServiceWorker.stopWorker', { versionId: version.versionId });
    popup = await newPage(); await popup.goto(popupUrl);
    await popup.locator('#connection-text').getByText('Engine Online', { exact: true }).waitFor({ timeout: 10000 });
    await popup.locator('#caep-status').getByText('TREASURY FROZEN (RFC 9493)', { exact: true }).waitFor();
    assert((await getStatus()).lastAlert);
    await meet.locator('#echo-barge-in-overlay').waitFor();
    pass('Worker wake-up automatically reconnects and retains the active fraud alert and bank lock');

    await popup.locator('#btn-review-treasury').click();
    assert.equal((await transaction()).is_locked, true);
    assert((await getStatus()).lastAlert);
    const active = await popup.evaluate(() => chrome.tabs.query({ active: true, currentWindow: true }));
    assert(active.some(tab => tab.url.startsWith('http://localhost:3000/')));
    pass('Review & release opens Treasury without falsely dismissing or unlocking the transaction');

    await meet.locator('#echo-btn-dismiss').click();
    await meet.locator('#echo-barge-in-overlay').waitFor({ state: 'detached' });
    await local.locator('#echo-barge-in-overlay').waitFor({ state: 'detached' });
    assert.equal((await transaction()).is_locked, true);
    await popup.locator('#caep-status').getByText('TREASURY FROZEN (RFC 9493)', { exact: true }).waitFor();
    assert(await bank.locator('#echo-treasury-banner').isVisible());
    pass('Call alert dismissal clears both call overlays but preserves bank freeze and its banner');
    await releaseBank();
    await bank.locator('#echo-treasury-banner').waitFor({ state: 'detached' });
    await popup.locator('#caep-status').getByText('TREASURY NOT FROZEN', { exact: true }).waitFor();
    assert.equal((await transaction()).is_locked, false);
    pass('Verified operator release synchronizes the popup, bank banner, and backend ledger');

    await popup.locator('#toggle-settings').click();
    await popup.locator('#ws-url-input').fill('ws://127.0.0.1:9/ws/call');
    await popup.locator('#btn-save-settings').click();
    await popup.locator('#connection-text').getByText('Offline', { exact: true }).waitFor();
    await local.locator('#echo-hud-status-badge').getByText('OFFLINE', { exact: true }).waitFor();
    await popup.locator('#caep-status').getByText('TREASURY STATUS UNAVAILABLE', { exact: true }).waitFor();
    await popup.locator('#toggle-settings').click();
    await popup.locator('#ws-url-input').fill('ws://localhost:8000/ws/call');
    await popup.locator('#btn-save-settings').click();
    await popup.locator('#connection-text').getByText('Engine Online', { exact: true }).waitFor();
    await local.locator('#echo-hud-status-badge').getByText('SECURE', { exact: true }).waitFor();
    pass('Offline monitoring is visible and settings reconnect replaces old sockets safely');

    // No popup polling during this interval: heartbeats must retain the active worker/session.
    await meet.evaluate(() => { document.getElementById('test-caption').textContent = 'Hello again, the meeting is continuing normally.'; });
    const beforeQuiet = await poll(getStatus, status => status.activeSessionId && status.history.some(turn => turn.text.includes('Hello again')));
    await popup.close();
    console.log('Checking a quiet 35-second interval without popup polling...');
    await wait(35000);
    popup = await newPage(); await popup.goto(popupUrl);
    const afterQuiet = await getStatus();
    assert.equal(afterQuiet.connectionStatus, 'connected');
    assert.equal(afterQuiet.activeSessionId, beforeQuiet.activeSessionId);
    pass('Quiet monitoring retains the same backend session beyond the MV3 idle window');
    assert.deepEqual(report.browserErrors, []);
    report.finalTransaction = { locked: (await transaction()).is_locked };
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.failure = error.message;
    for (const [name, page] of [['meet', meet], ['bank', bank], ['popup', popup]]) if (page && !page.isClosed()) await page.screenshot({ path: path.join(out, name + '-failure.png'), fullPage: true }).catch(() => {});
    if (sentAttack && bank && (await transaction()).is_locked) await releaseBank().catch(() => {});
    throw error;
  } finally {
    report.finished = new Date().toISOString();
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    console.log('Report: ' + path.join(out, 'report.json'));
    await context.close();
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
