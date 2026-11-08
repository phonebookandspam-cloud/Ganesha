import fs from 'node:fs';
import crypto from 'node:crypto';

const baseUrl = process.env.GANESHA_AUDIO_QA_BASE_URL || 'http://127.0.0.1:8787';
const cdp = process.env.GANESHA_AUDIO_QA_CDP || 'http://127.0.0.1:9222';
const reportPath = process.env.GANESHA_AUDIO_QA_OUTPUT || 'artifacts/BROWSER_AUDIO_KEYBOARD_QA_20261104_R17_LAYOUT_V2.json';
if (fs.existsSync(reportPath)) throw new Error(`refusing to overwrite existing QA artifact: ${reportPath}`);

class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.nextId = 0;
    this.pending = new Map();
    this.handlers = new Map();
    this.ready = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });
    this.ws.addEventListener('message', async (event) => {
      const message = JSON.parse(typeof event.data === 'string' ? event.data : await event.data.text());
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(`${message.error.code}: ${message.error.message}`));
        else resolve(message.result || {});
      } else if (message.method) {
        for (const handler of this.handlers.get(message.method) || []) handler(message.params || {});
      }
    });
  }
  on(method, handler) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(handler);
  }
  async call(method, params = {}) {
    await this.ready;
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  close() { this.ws.close(); }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const waitFor = async (fn, timeoutMs, label) => {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = await fn();
    if (value) return value;
    await sleep(100);
  }
  throw new Error(`timeout waiting for ${label}`);
};

const targetResponse = await fetch(`${cdp}/json/new?about:blank`, { method: 'PUT' });
if (!targetResponse.ok) throw new Error(`Chrome target creation failed: ${targetResponse.status}`);
const target = await targetResponse.json();
const page = new CDP(target.webSocketDebuggerUrl);
const browser = new CDP((await (await fetch(`${cdp}/json/version`)).json()).webSocketDebuggerUrl);
const network = [];
const failedRequests = [];
const consoleErrors = [];
const exceptions = [];
page.on('Network.responseReceived', (event) => network.push({ url: event.response.url, status: event.response.status }));
page.on('Network.loadingFailed', (event) => failedRequests.push({ requestId: event.requestId, errorText: event.errorText }));
page.on('Runtime.exceptionThrown', (event) => exceptions.push(event.exceptionDetails?.text || event.exceptionDetails?.exception?.description || 'unknown exception'));
page.on('Runtime.consoleAPICalled', (event) => {
  if (event.type === 'error' || event.type === 'assert') consoleErrors.push((event.args || []).map((item) => item.value ?? item.description ?? '').join(' '));
});

const evaluate = async (expression) => {
  const result = await page.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'page evaluation failed');
  return result.result?.value;
};

let report;
try {
  await page.call('Page.enable');
  await page.call('Page.bringToFront');
  await browser.call('Target.activateTarget', { targetId: target.id });
  await page.call('Runtime.enable');
  await page.call('Network.enable');
  await page.call('Log.enable');
  await page.call('Page.addScriptToEvaluateOnNewDocument', { source: `
    (() => {
      window.__ganeshaAudioPlayLog = [];
      const originalPlay = HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play = function() {
        const record = { src: this.currentSrc || this.src || '', resolved: false, error: null, at: performance.now(), snapshot: () => ({ readyState: this.readyState, networkState: this.networkState, paused: this.paused, currentTime: this.currentTime, duration: this.duration, mediaError: this.error?.code ?? null, connected: this.isConnected }) };
        window.__ganeshaAudioPlayLog.push(record);
        let result;
        try { result = originalPlay.call(this); }
        catch (error) { record.error = String(error); throw error; }
        if (result && typeof result.then === 'function') {
          return result.then(value => { record.resolved = true; return value; }, error => { record.error = String(error); throw error; });
        }
        record.resolved = true;
        return result;
      };
    })();
  `});
  const loaded = new Promise((resolve) => page.on('Page.loadEventFired', resolve));
  await page.call('Page.navigate', { url: baseUrl });
  await loaded;
  await waitFor(() => evaluate(`document.readyState === 'complete' && !!document.querySelector('#sound-toggle') && !!document.querySelector('#engine-fixture-button') && !document.querySelector('#engine-fixture-button').disabled`), 15000, 'preview controls ready');

  await evaluate(`document.querySelector('.skip-link').focus(); true`);
  await page.call('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await page.call('Input.dispatchKeyEvent', { type: 'char', key: 'Enter', code: 'Enter', text: '\r', unmodifiedText: '\r', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await page.call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await waitFor(() => evaluate(`location.hash === '#game-preview' && document.activeElement?.id === 'game-preview'`), 3000, 'skip link moves keyboard focus to main preview');
  const skipLinkEvidence = await evaluate(`({hash:location.hash,activeElement:document.activeElement?.id,tabIndex:document.querySelector('#game-preview').tabIndex})`);

  await evaluate(`window.__toggleKeyEvents=[];document.querySelector('#sound-toggle').addEventListener('click',e=>window.__toggleKeyEvents.push({type:'click',trusted:e.isTrusted}));document.querySelector('#sound-toggle').addEventListener('keydown',e=>window.__toggleKeyEvents.push({type:'keydown',key:e.key,trusted:e.isTrusted}));document.querySelector('#sound-toggle').addEventListener('keyup',e=>window.__toggleKeyEvents.push({type:'keyup',key:e.key,trusted:e.isTrusted}));true`);
  const beforeKeyboard = await evaluate(`({pressed:document.querySelector('#sound-toggle').getAttribute('aria-pressed'),tag:document.querySelector('#sound-toggle').tagName,disabled:document.querySelector('#sound-toggle').disabled})`);
  await evaluate(`document.querySelector('#sound-toggle').focus(); true`);
  await page.call('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await page.call('Input.dispatchKeyEvent', { type: 'char', key: 'Enter', code: 'Enter', text: '\r', unmodifiedText: '\r', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await page.call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await sleep(250);
  const afterKeyboard = await evaluate(`({pressed:document.querySelector('#sound-toggle').getAttribute('aria-pressed'),activeElement:document.activeElement?.id,events:window.__toggleKeyEvents})`);
  if (afterKeyboard.pressed !== 'true') throw new Error('keyboard Enter did not activate sound toggle: ' + JSON.stringify(afterKeyboard));

  await evaluate(`document.querySelector('#engine-fixture-button').click(); true`);
  await waitFor(() => evaluate(`document.querySelector('#fixture-engine-state').textContent.trim() === 'COMPLETED'`), 90000, '90-event GameEngine fixture completion');
  await waitFor(() => evaluate(`window.__ganeshaAudioPlayLog.length >= 78 && window.__ganeshaAudioPlayLog.every(x => x.resolved || x.error)`), 15000, 'all 78 SFX play promises resolve or report error');

  const browserEvidence = await evaluate(`({
    soundToggle:{tag:document.querySelector('#sound-toggle').tagName,disabled:document.querySelector('#sound-toggle').disabled,pressed:document.querySelector('#sound-toggle').getAttribute('aria-pressed'),activeElement:document.activeElement?.id,keyEvents:window.__toggleKeyEvents},
    fixtureState:document.querySelector('#fixture-engine-state').textContent.trim(),
    eventCount:Number(document.querySelector('#fixture-event-count').textContent),
    eventNames:[...document.querySelectorAll('#fixture-event-history li')].map(x=>x.textContent.trim()),
    audio:window.__ganeshaAudioPlayLog.map(x=>({file:(x.src.split('/').pop()||''),resolved:x.resolved,error:x.error,...x.snapshot()})),
    audioErrors:window.__ganeshaAudioPlayLog.filter(x=>x.error)
  })`);
  const required = ['reel-stop.wav', 'wild-expansion.wav', 'free-spins.wav', 'win.wav'];
  const audio = Object.fromEntries(required.map((file) => {
    const attempts = browserEvidence.audio.filter((item) => item.file === file);
    return [file, { attempts: attempts.length, resolved: attempts.filter((item) => item.resolved).length, errors: attempts.filter((item) => item.error).map((item) => item.error) }];
  }));
  const sfxPass = required.every((file) => audio[file].attempts > 0 && audio[file].resolved === audio[file].attempts && audio[file].errors.length === 0);
  const eventCountPass = browserEvidence.fixtureState === 'COMPLETED' && browserEvidence.eventCount === 90 && browserEvidence.eventNames.length === 90;
  const skipLinkPass = skipLinkEvidence.hash === '#game-preview' && skipLinkEvidence.activeElement === 'game-preview' && skipLinkEvidence.tabIndex === -1;
  const keyboardPass = skipLinkPass && beforeKeyboard.tag === 'BUTTON' && !beforeKeyboard.disabled && beforeKeyboard.pressed === 'false' && browserEvidence.soundToggle.pressed === 'true';
  const httpErrors = network.filter((item) => item.status >= 400);
  report = {
    schema: 'ganesha-browser-audio-keyboard-qa.v2',
    url: baseUrl,
    browser: (await (await fetch(`${cdp}/json/version`)).json()).Browser,
    keyboard: { skipLink: { ...skipLinkEvidence, pass: skipLinkPass }, before: beforeKeyboard, after: browserEvidence.soundToggle, pass: keyboardPass },
    fixture: { state: browserEvidence.fixtureState, eventCount: browserEvidence.eventCount, eventNames: browserEvidence.eventNames, pass: eventCountPass },
    audio,
    audioPlaybackLog: browserEvidence.audio,
    consoleErrors,
    exceptions,
    network: { httpErrors, failedRequests },
    pass: Boolean(keyboardPass && eventCountPass && sfxPass && !browserEvidence.audioErrors.length && !consoleErrors.length && !exceptions.length && !httpErrors.length && !failedRequests.length),
    limitation: 'HTMLMediaElement.play() Promise resolution proves browser playback acceptance, not physical audibility, speaker output, or acoustic quality.'
  };
} catch (error) {
  let diagnostics = null;
  try { diagnostics = await evaluate(`({fixtureState:document.querySelector('#fixture-engine-state')?.textContent,fixtureStatus:document.querySelector('#fixture-status')?.textContent,eventCount:document.querySelector('#fixture-event-count')?.textContent,eventRows:document.querySelectorAll('#fixture-event-history li').length,message:document.querySelector('#message')?.textContent,fixtureButtonDisabled:document.querySelector('#engine-fixture-button')?.disabled,keyboard:{pressed:document.querySelector('#sound-toggle')?.getAttribute('aria-pressed'),activeElement:document.activeElement?.id,events:window.__toggleKeyEvents},userActivation:navigator.userActivation ? {hasBeenActive:navigator.userActivation.hasBeenActive,isActive:navigator.userActivation.isActive} : null,visibility:document.visibilityState,audio:window.__ganeshaAudioPlayLog?.map(x=>({src:x.src,resolved:x.resolved,error:x.error,...x.snapshot()}))})`); } catch {}
  report = { schema: 'ganesha-browser-audio-keyboard-qa.v2', url: baseUrl, pass: false, error: String(error), diagnostics, network, consoleErrors, exceptions, failedRequests };
} finally {
  try { await page.call('Page.close'); } catch {}
  page.close();
  browser.close();
  try { await fetch(`${cdp}/json/close/${target.id}`); } catch {}
}
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
const bytes = fs.readFileSync(reportPath);
console.log(JSON.stringify({ pass: report.pass, reportPath, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), keyboard: report.keyboard, fixture: report.fixture && { state: report.fixture.state, eventCount: report.fixture.eventCount, pass: report.fixture.pass }, audio: report.audio, consoleErrors: report.consoleErrors, exceptions: report.exceptions, error: report.error }, null, 2));
if (!report.pass) process.exitCode = 2;
