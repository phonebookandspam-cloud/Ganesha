import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const baseUrl = process.env.GANESHA_BROWSER_QA_BASE_URL || 'http://127.0.0.1:8795';
const cdp = 'http://127.0.0.1:9222';
const outputBase = process.env.GANESHA_BROWSER_QA_OUTPUT_BASE || 'artifacts/BROWSER_QA_20261104_INTEGRATION_R1_CURRENT';
const expectedHead = process.env.GANESHA_BROWSER_QA_EXPECTED_HEAD || 'a6e7997e469730f67c10b9f5657c5a1edfbfb2c2';
const reducedMotionRequested = process.env.GANESHA_BROWSER_QA_REDUCED_MOTION === '1';
const reportPath = `${outputBase}.json`;
const screenshotPaths = {
  fixtureDesktop: `${outputBase}_FIXTURE_DESKTOP.png`,
  runtimeDesktop: `${outputBase}_RUNTIME_DESKTOP.png`,
  runtimeMobile: `${outputBase}_RUNTIME_MOBILE.png`,
  runtimeLandscape: `${outputBase}_RUNTIME_LANDSCAPE.png`,
};
for (const file of [reportPath, ...Object.values(screenshotPaths)]) {
  if (fs.existsSync(file)) throw new Error(`refusing to overwrite existing QA artifact: ${file}`);
}

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
      const raw = typeof event.data === 'string' ? event.data : await event.data.text();
      const message = JSON.parse(raw);
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
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
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
page.on('Network.responseReceived', (event) => network.push({ url: event.response.url, status: event.response.status, mimeType: event.response.mimeType }));
page.on('Network.loadingFailed', (event) => failedRequests.push({ requestId: event.requestId, errorText: event.errorText, blockedReason: event.blockedReason || null }));
page.on('Runtime.exceptionThrown', (event) => exceptions.push(event.exceptionDetails?.text || event.exceptionDetails?.exception?.description || 'unknown exception'));
page.on('Runtime.consoleAPICalled', (event) => {
  if (event.type === 'error' || event.type === 'assert') consoleErrors.push((event.args || []).map((x) => x.value ?? x.description ?? '').join(' '));
});
page.on('Log.entryAdded', (event) => {
  if (event.entry?.level === 'error') consoleErrors.push(event.entry.text || 'browser log error');
});

const evaluate = async (expression) => {
  const result = await page.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'page evaluation failed');
  return result.result?.value;
};
const screenshot = async (file) => {
  const result = await page.call('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false });
  fs.writeFileSync(file, Buffer.from(result.data, 'base64'), { flag: 'wx' });
  return { path: file, size_bytes: fs.statSync(file).size, sha256: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') };
};
const viewport = async (width, height, mobile, orientation) => {
  await page.call('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: mobile ? 2 : 1, mobile,
    screenWidth: width, screenHeight: height,
    ...(orientation ? { screenOrientation: orientation } : {}),
  });
  await evaluate('window.dispatchEvent(new Event("resize")); true');
  await sleep(250);
  return evaluate(`({innerWidth,innerHeight,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,documentHeight:document.documentElement.scrollHeight,bodyHeight:document.body.scrollHeight,horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1||document.body.scrollWidth>innerWidth+1,boardCells:document.querySelectorAll('#board .symbol').length,brokenImages:[...document.images].filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.currentSrc||i.src)})`);
};

let report;
try {
  await page.call('Page.enable');
  await page.call('Runtime.enable');
  await page.call('Network.enable');
  await page.call('Log.enable');
  await page.call('Network.setCacheDisabled', { cacheDisabled: true });
  await page.call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: reducedMotionRequested ? 'reduce' : 'no-preference' }] });
  await page.call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  const loaded = new Promise((resolve) => page.on('Page.loadEventFired', resolve));
  await page.call('Page.navigate', { url: baseUrl });
  await loaded;
  await waitFor(() => evaluate(`document.readyState==='complete' && document.getElementById('engine-fixture-button') && !document.getElementById('engine-fixture-button').disabled`), 15000, 'frontend health and fixture control');
  const health = await (await fetch(`${baseUrl}/health`)).json();
  const launchConfig = await evaluate('window.GANESHA_CONFIG');
  await evaluate(`window.__ganeshaAnimationClasses=[];window.__ganeshaAnimationObserver=new MutationObserver(records=>{for(const record of records){const el=record.target;if(el instanceof Element){for(const name of ['wild-expansion-reveal','feature-start-reveal','event-pulse','multiplier-reveal','payout-reveal'])if(el.classList.contains(name))window.__ganeshaAnimationClasses.push(name)}}});window.__ganeshaAnimationObserver.observe(document.body,{attributes:true,attributeFilter:['class'],subtree:true});true`);

  const assetCheck = await evaluate(`(async()=>{
    const refs=['assets/a_icon_v15.svg','assets/chakra_icon_v15.svg','assets/elephant_icon_v15.svg','assets/ganesha_wild_v15.svg','assets/k_icon_v15.svg','assets/lotus_scatter_v15.svg','assets/modak_icon_v15.svg','assets/mouse_icon_v15.svg','assets/ganesha_temple_scene_v15.svg','assets/sfx/reel-stop.wav','assets/sfx/wild-expansion.wav','assets/sfx/free-spins.wav','assets/sfx/win.wav'];
    const results=[];
    for(const ref of refs){
      const response=await fetch('./'+ref,{cache:'no-store'});
      const item={path:ref,status:response.status,contentType:response.headers.get('content-type'),bytes:(await response.arrayBuffer()).byteLength};
      if(ref.endsWith('.svg')){
        const source=await (await fetch('./'+ref,{cache:'no-store'})).text();
        const doc=new DOMParser().parseFromString(source,'image/svg+xml');
        item.svgValid=doc.documentElement?.localName==='svg'&&!doc.querySelector('parsererror');
      }
      results.push(item);
    }
    return results;
  })()`);

  await evaluate(`document.getElementById('engine-fixture-button').click(); true`);
  await waitFor(() => evaluate(`document.getElementById('fixture-engine-state').textContent.trim()==='COMPLETED'`), 45000, 'GameEngine fixture normal completion');
  await waitFor(() => evaluate(`!document.getElementById('engine-fixture-button').disabled`), 5000, 'fixture UI returns to idle');
  const fixture = await evaluate(`({status:document.getElementById('fixture-status').textContent.trim(),engineState:document.getElementById('fixture-engine-state').textContent.trim(),featureProgress:document.getElementById('fixture-feature-progress').textContent.trim(),eventCount:Number(document.getElementById('fixture-event-count').textContent),payoutProjection:document.getElementById('fixture-payout').textContent.trim(),eventNames:[...document.querySelectorAll('#fixture-event-history li')].map(x=>x.textContent.trim()),boardLabels:[...document.querySelectorAll('#board .symbol small')].map(x=>x.textContent.trim()),boardCells:document.querySelectorAll('#board .symbol').length,message:document.getElementById('message').textContent.trim()})`);
  const fixtureScreenshot = await screenshot(screenshotPaths.fixtureDesktop);

  await evaluate(`document.getElementById('runtime-button').click(); true`);
  await waitFor(() => evaluate(`document.getElementById('runtime-status').textContent.trim()==='COMPLETED · NON-FINANCIAL'`), 45000, 'independent runtime normal completion');
  const runtime = await evaluate(`({status:document.getElementById('runtime-status').textContent.trim(),featureProgress:document.getElementById('runtime-feature-progress').textContent.trim(),payout:document.getElementById('runtime-payout').textContent.trim(),eventCount:Number(document.getElementById('runtime-event-count').textContent),eventNames:[...document.querySelectorAll('#runtime-event-history li')].map(x=>x.textContent.trim()),boardLabels:[...document.querySelectorAll('#board .symbol small')].map(x=>x.textContent.trim()),boardCells:document.querySelectorAll('#board .symbol').length})`);
  const runtimeDesktopMetrics = await viewport(1440, 1000, false);
  const runtimeScreenshot = await screenshot(screenshotPaths.runtimeDesktop);
  const mobileMetrics = await viewport(390, 844, true, { type: 'portraitPrimary', angle: 0 });
  const mobileScreenshot = await screenshot(screenshotPaths.runtimeMobile);
  const landscapeMetrics = await viewport(844, 390, true, { type: 'landscapePrimary', angle: 90 });
  const landscapeScreenshot = await screenshot(screenshotPaths.runtimeLandscape);
  await sleep(750);
  const animationEvidence = await evaluate(`({reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches,classes:[...new Set(window.__ganeshaAnimationClasses)],activeClasses:[...document.querySelectorAll('.wild-expansion-reveal,.feature-start-reveal,.event-pulse,.multiplier-reveal,.payout-reveal')].map(x=>x.className)})`);
  const expectedAnimationClasses = ['wild-expansion-reveal','feature-start-reveal','event-pulse','multiplier-reveal','payout-reveal'];
  const animationPass = animationEvidence.reducedMotion
    ? animationEvidence.activeClasses.length === 0
    : expectedAnimationClasses.every((name) => animationEvidence.classes.includes(name)) && animationEvidence.activeClasses.length === 0;

  const externalRequests = network.filter((x) => !x.url.startsWith(baseUrl) && !x.url.startsWith('data:'));
  const httpErrors = network.filter((x) => x.status >= 400);
  const assetFailures = assetCheck.filter((x) => x.status !== 200 || (x.path.endsWith('.svg') && !x.svgValid));
  const fixtureExpectedTypes = ['BASE_OUTCOME_REVEALED','FEATURE_STARTED','WILD_EXPANSION_APPLIED','MULTIPLIER_APPLIED','FEATURE_SPIN_RESOLVED','FEATURE_ENDED','ROUND_PRESENTATION_COMPLETED'];
  const fixtureTypesPresent = fixtureExpectedTypes.every((type) => fixture.eventNames.some((name) => name.includes(type.replace(/_/g,' '))));
  const viewportPass = [runtimeDesktopMetrics,mobileMetrics,landscapeMetrics].every((x) => !x.horizontalOverflow && x.brokenImages.length===0 && x.boardCells===15);
  const fixturePass = fixture.status==='COMPLETED · FIXTURE ONLY' && fixture.engineState==='COMPLETED'
    && fixture.featureProgress==='10 / 10 played · 0 remaining' && fixture.eventCount===fixture.eventNames.length
    && fixture.boardCells===15 && fixtureTypesPresent && fixture.payoutProjection.endsWith('milli-units · test only');
  const runtimePass = runtime.status==='COMPLETED · NON-FINANCIAL' && runtime.featureProgress==='10 / 10 played · 0 remaining'
    && runtime.eventCount===runtime.eventNames.length && runtime.boardCells===15;
  report = {
    schema: 'ganesha-current-head-browser-qa.v1',
    source: { head: expectedHead, branch: 'main', url: baseUrl },
    browser: (await (await fetch(`${cdp}/json/version`)).json()).Browser,
    health, launchConfig,
    fixture: { ...fixture, pass: fixturePass, screenshot: fixtureScreenshot },
    independentRuntime: { ...runtime, pass: runtimePass },
    viewports: { desktop: runtimeDesktopMetrics, mobile: mobileMetrics, landscape: landscapeMetrics, pass: viewportPass },
    assets: { checked: assetCheck.length, results: assetCheck, failures: assetFailures },
    network: { responses: network, httpErrors, failedRequests, externalRequests },
    console: { errors: consoleErrors, exceptions },
    animations: { ...animationEvidence, requestedReducedMotion: reducedMotionRequested, expected: expectedAnimationClasses, pass: animationPass },
    screenshots: { fixtureDesktop: fixtureScreenshot, runtimeDesktop: runtimeScreenshot, runtimeMobile: mobileScreenshot, runtimeLandscape: landscapeScreenshot },
    pass: Boolean(health.status==='ok' && fixturePass && runtimePass && viewportPass && animationPass && !assetFailures.length
      && !httpErrors.length && !failedRequests.length && !externalRequests.length && !consoleErrors.length && !exceptions.length),
    classification: 'NON_FINANCIAL_TEST_FIXTURE_AND_INDEPENDENT_DRAFT_MATH_SIMULATION_ONLY; NOT_STAKE_RGS_OR_PRODUCTION_WALLET'
  };
} catch (error) {
  report = { schema: 'ganesha-current-head-browser-qa.v1', source: { head: expectedHead, branch: 'main', url: baseUrl }, pass: false, error: String(error), network, failedRequests, consoleErrors, exceptions };
} finally {
  try { await page.call('Page.close'); } catch {}
  page.close();
  browser.close();
  try { await fetch(`${cdp}/json/close/${target.id}`); } catch {}
}
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
console.log(JSON.stringify({ pass: report.pass, reportPath, fixture: report.fixture, runtime: report.independentRuntime, viewports: report.viewports, animations: report.animations, assetFailures: report.assets?.failures, httpErrors: report.network?.httpErrors, failedRequests: report.network?.failedRequests, console: report.console }, null, 2));
if (!report.pass) process.exitCode = 2;
