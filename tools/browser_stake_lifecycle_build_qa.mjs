import fs from 'node:fs';
import crypto from 'node:crypto';

const baseUrl = 'http://127.0.0.1:8787';
const cdp = 'http://127.0.0.1:9222';
const output = 'artifacts/BROWSER_STAKE_LIFECYCLE_BUILD_20261104_A6E7997_R4';
const reportPath = output + '.json';
const screenshots = {
  desktop: output + '_DESKTOP.png',
  mobile: output + '_MOBILE.png',
  landscape: output + '_LANDSCAPE.png',
};
for (const file of [reportPath, ...Object.values(screenshots)]) {
  if (fs.existsSync(file)) throw new Error('refusing to overwrite existing browser QA artifact: ' + file);
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
        const entry = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) entry.reject(new Error(message.error.message));
        else entry.resolve(message.result || {});
      } else if (message.method) {
        for (const handler of this.handlers.get(message.method) || []) handler(message.params || {});
      }
    });
  }
  on(method, callback) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(callback);
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
  throw new Error('timeout waiting for ' + label);
};

const targetResponse = await fetch(cdp + '/json/new?about:blank', { method: 'PUT' });
if (!targetResponse.ok) throw new Error('Chrome target creation failed: ' + targetResponse.status);
const target = await targetResponse.json();
const page = new CDP(target.webSocketDebuggerUrl);
const browser = new CDP((await (await fetch(cdp + '/json/version')).json()).webSocketDebuggerUrl);
const network = [];
const failedRequests = [];
const consoleErrors = [];
const exceptions = [];
page.on('Network.responseReceived', (event) => network.push({ url: event.response.url, status: event.response.status, mimeType: event.response.mimeType }));
page.on('Network.loadingFailed', (event) => failedRequests.push({ errorText: event.errorText, blockedReason: event.blockedReason || null }));
page.on('Runtime.exceptionThrown', (event) => exceptions.push(event.exceptionDetails?.text || event.exceptionDetails?.exception?.description || 'unknown exception'));
page.on('Runtime.consoleAPICalled', (event) => {
  if (event.type === 'error' || event.type === 'assert') consoleErrors.push((event.args || []).map((item) => item.value ?? item.description ?? '').join(' '));
});
page.on('Log.entryAdded', (event) => { if (event.entry?.level === 'error') consoleErrors.push(event.entry.text || 'browser log error'); });

const evaluate = async (expression) => {
  const result = await page.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'page evaluation failed');
  return result.result?.value;
};
const screenshot = async (file) => {
  const result = await page.call('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false });
  fs.writeFileSync(file, Buffer.from(result.data, 'base64'), { flag: 'wx' });
  const bytes = fs.readFileSync(file);
  return { path: file, size_bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
};
const viewport = async (width, height, mobile, orientation) => {
  await page.call('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: mobile ? 2 : 1, mobile,
    screenWidth: width, screenHeight: height,
    ...(orientation ? { screenOrientation: orientation } : {}),
  });
  await evaluate('window.dispatchEvent(new Event("resize")); true');
  await sleep(200);
  return evaluate(`({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,
    horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1||document.body.scrollWidth>innerWidth+1,
    brokenImages:[...document.images].filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.currentSrc||i.src),
    boardCells:document.querySelectorAll('#board .symbol').length,
    reconnectButtonVisible:!document.getElementById('stake-reconnect-button').hidden})`);
};

let report;
try {
  await page.call('Page.enable');
  await page.call('Runtime.enable');
  await page.call('Network.enable');
  await page.call('Log.enable');
  await page.call('Network.setCacheDisabled', { cacheDisabled: true });
  await page.call('Page.addScriptToEvaluateOnNewDocument', { source: `(() => {
    const nativeFetch = window.fetch.bind(window);
    window.__stakeLifecycleRequests = [];
    let authenticateCount = 0;
    const jurisdiction = { socialCasino:false, disabledFullscreen:false, disabledTurbo:false,
      disabledSuperTurbo:false, disabledAutoplay:false, disabledSlamstop:false,
      disabledSpacebar:false, disabledBuyFeature:true, displayNetPosition:true,
      displayRTP:true, displaySessionTimer:true, minimumRoundDuration:0 };
    const config = { minBet:100000, maxBet:1000000, stepBet:100000,
      defaultBetLevel:100000, betLevels:[100000,200000,500000,1000000], jurisdiction };
    window.fetch = async (input, init = {}) => {
      const url = String(input);
      const method = (init.method || 'GET').toUpperCase();
      if (url === 'https://mock-rgs.example/wallet/authenticate' && method === 'POST') {
        authenticateCount += 1;
        window.__stakeLifecycleRequests.push({ path:'/wallet/authenticate', body:JSON.parse(init.body || '{}') });
        const round = authenticateCount === 1 ? { betID:441, active:true, mode:'BASE',
          payoutMultiplier:0, state:[{ event:'server-owned-opaque-state', marker:'not-decoded-by-client' }] } : null;
        return new Response(JSON.stringify({ balance:{amount:1250000,currency:'USD'}, config, round }),
          { status:200, headers:{'Content-Type':'application/json'} });
      }
      if (url.startsWith('https://mock-rgs.example/')) {
        window.__stakeLifecycleRequests.push({ path:new URL(url).pathname, body:init.body || null });
        return new Response(JSON.stringify({ error:'unexpected financial request in browser QA' }),
          { status:403, headers:{'Content-Type':'application/json'} });
      }
      return nativeFetch(input, init);
    };
  })();` });
  await page.call('Emulation.setDeviceMetricsOverride', { width:1440, height:1000, deviceScaleFactor:1, mobile:false });
  const loaded = new Promise((resolve) => page.on('Page.loadEventFired', resolve));
  await page.call('Page.navigate', { url: baseUrl + '/?sessionID=browser-lifecycle-session&rgs_url=mock-rgs.example&lang=ja&device=desktop' });
  await loaded;
  await waitFor(() => evaluate(`document.getElementById('stake-session-status')?.textContent.includes('ACTIVE ROUND 441')`), 15000, 'active Stake round restore');
  const initial = await evaluate(`({connection:document.getElementById('connection-label').textContent,
    status:document.getElementById('stake-session-status').textContent,
    balance:document.getElementById('stake-balance').textContent,
    reconnectDisabled:document.getElementById('stake-reconnect-button').disabled,
    allWagerControlsDisabled:[...document.querySelectorAll('button:not(#sound-toggle):not(#stake-reconnect-button)')].every(b=>b.disabled),
    calls:window.__stakeLifecycleRequests.slice()})`);
  await evaluate(`document.getElementById('stake-reconnect-button').click(); true`);
  await waitFor(() => evaluate(`document.getElementById('stake-session-status')?.textContent.includes('NO ACTIVE ROUND')`), 15000, 'fresh Authenticate after reconnect');
  const afterReconnect = await evaluate(`({connection:document.getElementById('connection-label').textContent,
    status:document.getElementById('stake-session-status').textContent,
    balance:document.getElementById('stake-balance').textContent,
    reconnectDisabled:document.getElementById('stake-reconnect-button').disabled,
    calls:window.__stakeLifecycleRequests.slice()})`);
  const assets = await evaluate(`(async()=>{
    const paths=['assets/a_icon_v14.svg','assets/chakra_icon_v14.svg','assets/elephant_icon_v14.svg',
      'assets/ganesha_wild_v14.svg','assets/k_icon_v14.svg','assets/lotus_scatter_v14.svg',
      'assets/modak_icon_v14.svg','assets/mouse_icon_v14.svg','assets/ganesha_temple_scene_v14.png',
      'assets/reel-stop.wav','assets/wild-expansion.wav','assets/free-spins.wav','assets/win.wav'];
    const values=[];
    for(const path of paths){const r=await fetch('./'+path,{cache:'no-store'});const bytes=await r.arrayBuffer();
      const item={path,status:r.status,bytes:bytes.byteLength};
      if(path.endsWith('.svg')){const doc=new DOMParser().parseFromString(new TextDecoder().decode(bytes),'image/svg+xml');item.svgValid=doc.documentElement?.localName==='svg'&&!doc.querySelector('parsererror');}
      values.push(item);}
    return values;
  })()`);
  const desktopMetrics = await viewport(1440,1000,false);
  const desktopScreenshot = await screenshot(screenshots.desktop);
  const mobileMetrics = await viewport(390,844,true,{type:'portraitPrimary',angle:0});
  const mobileScreenshot = await screenshot(screenshots.mobile);
  const landscapeMetrics = await viewport(844,390,true,{type:'landscapePrimary',angle:90});
  const landscapeScreenshot = await screenshot(screenshots.landscape);
  const finalCalls = await evaluate('window.__stakeLifecycleRequests.slice()');
  const financialCalls = finalCalls.filter((item) => item.path !== '/wallet/authenticate');
  const viewportPass = [desktopMetrics,mobileMetrics,landscapeMetrics].every((item) => !item.horizontalOverflow && !item.brokenImages.length && item.boardCells === 15);
  const pass = initial.status.includes('ACTIVE ROUND 441') && afterReconnect.status.includes('NO ACTIVE ROUND')
    && initial.calls.length===1 && afterReconnect.calls.length===2 && financialCalls.length===0
    && initial.allWagerControlsDisabled && viewportPass && assets.length===13
    && assets.every((item)=>item.status===200 && (item.svgValid===undefined || item.svgValid))
    && !failedRequests.length && !consoleErrors.length && !exceptions.length;
  report = {
    schema:'ganesha.stake-sdk-lifecycle-build-browser-qa.v1',
    source:{head:'a6e7997e469730f67c10b9f5657c5a1edfbfb2c2',branch:'main',build:'artifacts/FRONTEND_BUILD_CURRENT_HEAD_A6E7997_LIFECYCLE_04',url:baseUrl},
    browser:(await (await fetch(cdp+'/json/version')).json()).Browser,
    initial, afterReconnect, sdkCalls:finalCalls, financialCalls,
    viewports:{desktop:desktopMetrics,mobile:mobileMetrics,landscape:landscapeMetrics,pass:viewportPass},
    assets:{checked:assets.length,results:assets},
    network:{responses:network,failedRequests},console:{errors:consoleErrors,exceptions},
    screenshots:{desktop:desktopScreenshot,mobile:mobileScreenshot,landscape:landscapeScreenshot},
    pass,classification:'CURRENT_BUILD_BROWSER_VERIFICATION_WITH_MOCKED_AUTHENTICATE_ONLY; NO_PROVIDER_OR_WAGERING'
  };
} catch (error) {
  report = { schema:'ganesha.stake-sdk-lifecycle-build-browser-qa.v1', pass:false, error:String(error), network, failedRequests, consoleErrors, exceptions };
} finally {
  try { await page.call('Page.close'); } catch {}
  page.close();
  browser.close();
  try { await fetch(cdp+'/json/close/'+target.id); } catch {}
}
fs.writeFileSync(reportPath, JSON.stringify(report,null,2)+'\n', { flag:'wx' });
console.log(JSON.stringify({pass:report.pass,reportPath,initial:report.initial,afterReconnect:report.afterReconnect,
  viewports:report.viewports,financialCalls:report.financialCalls,assets:report.assets?.checked,
  failedRequests:report.network?.failedRequests,console:report.console},null,2));
if (!report.pass) process.exitCode=2;
