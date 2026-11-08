import fs from 'node:fs';
import crypto from 'node:crypto';

const baseUrl = 'http://127.0.0.1:8787';
const cdp = 'http://127.0.0.1:9222';
const output = 'artifacts/BROWSER_RUNTIME_RECOVERY_20261104_A6E7997_R2';
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
    this.ws = new WebSocket(url); this.nextId = 0; this.pending = new Map(); this.handlers = new Map();
    this.ready = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });
    this.ws.addEventListener('message', async (event) => {
      const message = JSON.parse(typeof event.data === 'string' ? event.data : await event.data.text());
      if (message.id && this.pending.has(message.id)) {
        const pending = this.pending.get(message.id); this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message)); else pending.resolve(message.result || {});
      } else if (message.method) for (const handler of this.handlers.get(message.method) || []) handler(message.params || {});
    });
  }
  on(method, handler) { if (!this.handlers.has(method)) this.handlers.set(method, []); this.handlers.get(method).push(handler); }
  async call(method, params = {}) {
    await this.ready; const id = ++this.nextId;
    return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  close() { this.ws.close(); }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const waitFor = async (fn, timeoutMs, label) => {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) { const value = await fn(); if (value) return value; await sleep(100); }
  throw new Error('timeout waiting for ' + label);
};

const targetResponse = await fetch(cdp + '/json/new?about:blank', { method: 'PUT' });
if (!targetResponse.ok) throw new Error('Chrome target creation failed: ' + targetResponse.status);
const target = await targetResponse.json();
const page = new CDP(target.webSocketDebuggerUrl);
const browser = new CDP((await (await fetch(cdp + '/json/version')).json()).webSocketDebuggerUrl);
const network = []; const failedRequests = []; const consoleErrors = []; const exceptions = [];
page.on('Network.responseReceived', (event) => network.push({ url:event.response.url,status:event.response.status,mimeType:event.response.mimeType }));
page.on('Network.loadingFailed', (event) => failedRequests.push({ errorText:event.errorText,blockedReason:event.blockedReason||null }));
page.on('Runtime.exceptionThrown', (event) => exceptions.push(event.exceptionDetails?.text||event.exceptionDetails?.exception?.description||'unknown exception'));
page.on('Runtime.consoleAPICalled', (event) => { if(event.type==='error'||event.type==='assert') consoleErrors.push((event.args||[]).map(x=>x.value??x.description??'').join(' ')); });
page.on('Log.entryAdded', (event) => { if(event.entry?.level==='error') consoleErrors.push(event.entry.text||'browser log error'); });

const evaluate = async (expression) => {
  const result = await page.call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails) throw new Error(result.exceptionDetails.text||'page evaluation failed');
  return result.result?.value;
};
const screenshot = async (file) => {
  const result = await page.call('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
  fs.writeFileSync(file,Buffer.from(result.data,'base64'),{flag:'wx'});
  const bytes=fs.readFileSync(file); return {path:file,size_bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
};
const viewport = async (width,height,mobile,orientation) => {
  await page.call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:mobile?2:1,mobile,screenWidth:width,screenHeight:height,...(orientation?{screenOrientation:orientation}:{})});
  await evaluate('window.dispatchEvent(new Event("resize"));true'); await sleep(200);
  return evaluate(`({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,
    horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1||document.body.scrollWidth>innerWidth+1,
    brokenImages:[...document.images].filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.currentSrc||i.src),
    boardCells:document.querySelectorAll('#board .symbol').length})`);
};

let report;
try {
  await page.call('Page.enable'); await page.call('Runtime.enable'); await page.call('Network.enable'); await page.call('Log.enable');
  await page.call('Network.setCacheDisabled',{cacheDisabled:true});
  await page.call('Page.addScriptToEvaluateOnNewDocument',{source:`(() => {
    const nativeFetch=window.fetch.bind(window);
    window.__runtimePostAttempts=[]; window.__runtimeSnapshotReads=[]; window.__runtimeFailNext='after-commit';
    window.fetch=async(input,init={})=>{
      const url=String(input); const method=(init.method||'GET').toUpperCase();
      const match=url.match(/\\/api\\/runtime\\/sessions\\/([a-f0-9]{32})(?:\\/rounds)?$/);
      if(match && method==='GET' && url.includes('/api/runtime/sessions/')) window.__runtimeSnapshotReads.push(match[1]);
      if(match && method==='POST' && url.endsWith('/rounds')){
        const body=JSON.parse(init.body||'{}'); const failure=window.__runtimeFailNext; window.__runtimeFailNext=null;
        window.__runtimePostAttempts.push({session_id:match[1],request_id:body.request_id,failure});
        if(failure==='before-commit') throw new TypeError('simulated browser transport loss before request dispatch');
        const response=await nativeFetch(input,init);
        if(failure==='after-commit') throw new TypeError('simulated browser response lost after server commit');
        return response;
      }
      return nativeFetch(input,init);
    };
  })();`});
  await page.call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  const loaded=new Promise(resolve=>page.on('Page.loadEventFired',resolve));
  await page.call('Page.navigate',{url:baseUrl}); await loaded;
  await waitFor(()=>evaluate(`document.getElementById('runtime-button')&&!document.getElementById('runtime-button').disabled`),15000,'runtime API availability');

  await evaluate(`document.getElementById('runtime-button').click();true`);
  await waitFor(()=>evaluate(`document.getElementById('runtime-status').textContent.trim()==='COMPLETED · NON-FINANCIAL'`),45000,'runtime recovery after committed response loss');
  const afterCommitLoss=await evaluate(`({status:document.getElementById('runtime-status').textContent.trim(),
    featureProgress:document.getElementById('runtime-feature-progress').textContent.trim(),
    payout:document.getElementById('runtime-payout').textContent.trim(),
    eventCount:Number(document.getElementById('runtime-event-count').textContent),
    events:[...document.querySelectorAll('#runtime-event-history li')].map(x=>x.textContent.trim()),
    postAttempts:window.__runtimePostAttempts.slice(),snapshotReads:window.__runtimeSnapshotReads.slice(),
    pendingStorage:sessionStorage.getItem('ganesha.runtime.pending.v1:'+window.GANESHA_CONFIG.roundEndpoint)})`);

  await evaluate(`window.__runtimeFailNext='before-commit';document.getElementById('runtime-button').click();true`);
  await waitFor(()=>evaluate(`document.getElementById('runtime-status').textContent.trim()==='COMPLETED · NON-FINANCIAL'`),45000,'runtime same-request retry after pre-dispatch failure');
  const beforeCommitLoss=await evaluate(`({status:document.getElementById('runtime-status').textContent.trim(),
    featureProgress:document.getElementById('runtime-feature-progress').textContent.trim(),
    eventCount:Number(document.getElementById('runtime-event-count').textContent),
    postAttempts:window.__runtimePostAttempts.slice(),snapshotReads:window.__runtimeSnapshotReads.slice(),
    pendingStorage:sessionStorage.getItem('ganesha.runtime.pending.v1:'+window.GANESHA_CONFIG.roundEndpoint)})`);

  const desktopMetrics=await viewport(1440,1000,false); const desktopShot=await screenshot(screenshots.desktop);
  const mobileMetrics=await viewport(390,844,true,{type:'portraitPrimary',angle:0}); const mobileShot=await screenshot(screenshots.mobile);
  const landscapeMetrics=await viewport(844,390,true,{type:'landscapePrimary',angle:90}); const landscapeShot=await screenshot(screenshots.landscape);
  const health=await (await fetch(baseUrl+'/health')).json();
  const assetResults=await evaluate(`(async()=>{const refs=['assets/a_icon_v14.svg','assets/chakra_icon_v14.svg','assets/elephant_icon_v14.svg','assets/ganesha_wild_v14.svg','assets/k_icon_v14.svg','assets/lotus_scatter_v14.svg','assets/modak_icon_v14.svg','assets/mouse_icon_v14.svg','assets/ganesha_temple_scene_v14.png','assets/sfx/reel-stop.wav','assets/sfx/wild-expansion.wav','assets/sfx/free-spins.wav','assets/sfx/win.wav'];const out=[];for(const ref of refs){const r=await fetch('./'+ref,{cache:'no-store'});const b=await r.arrayBuffer();const x={path:ref,status:r.status,bytes:b.byteLength};if(ref.endsWith('.svg')){const d=new DOMParser().parseFromString(new TextDecoder().decode(b),'image/svg+xml');x.svgValid=d.documentElement?.localName==='svg'&&!d.querySelector('parsererror');}out.push(x);}return out;})()`);
  const viewportPass=[desktopMetrics,mobileMetrics,landscapeMetrics].every(x=>!x.horizontalOverflow&&!x.brokenImages.length&&x.boardCells===15);
  const firstAttempt=afterCommitLoss.postAttempts.length===1&&afterCommitLoss.postAttempts[0].failure==='after-commit';
  const secondAttempts=beforeCommitLoss.postAttempts.slice(1);
  const sameRequestRetry=secondAttempts.length===2&&secondAttempts[0].failure==='before-commit'
    &&secondAttempts[1].failure===null&&secondAttempts[0].session_id===secondAttempts[1].session_id
    &&secondAttempts[0].request_id===secondAttempts[1].request_id;
  const pass=health.status==='ok'&&health.round_api_enabled===false
    &&afterCommitLoss.status==='COMPLETED · NON-FINANCIAL'&&afterCommitLoss.featureProgress==='10 / 10 played · 0 remaining'
    &&afterCommitLoss.eventCount===90&&firstAttempt&&afterCommitLoss.snapshotReads.length>=1&&afterCommitLoss.pendingStorage===null
    &&beforeCommitLoss.status==='COMPLETED · NON-FINANCIAL'&&beforeCommitLoss.featureProgress==='10 / 10 played · 0 remaining'
    &&beforeCommitLoss.eventCount===90&&sameRequestRetry&&beforeCommitLoss.pendingStorage===null
    &&viewportPass&&assetResults.length===13&&assetResults.every(x=>x.status===200&&(x.svgValid===undefined||x.svgValid))
    &&!failedRequests.length&&!consoleErrors.length&&!exceptions.length;
  report={schema:'ganesha.runtime.browser-recovery-qa.v1',source:{head:'a6e7997e469730f67c10b9f5657c5a1edfbfb2c2',branch:'main',frontend:'current shared workspace served by dev_server.py',url:baseUrl},
    browser:(await(await fetch(cdp+'/json/version')).json()).Browser,health,afterCommitLoss,beforeCommitLoss,
    viewports:{desktop:desktopMetrics,mobile:mobileMetrics,landscape:landscapeMetrics,pass:viewportPass},
    assets:{checked:assetResults.length,results:assetResults},network:{responses:network,failedRequests},console:{errors:consoleErrors,exceptions},
    screenshots:{desktop:desktopShot,mobile:mobileShot,landscape:landscapeShot},
    pass,classification:'NON_FINANCIAL_RUNTIME_ONLY; MOCKED_BROWSER_TRANSPORT_FAILURES; LOCAL_SQLITE; NO_WAGER_OR_PROVIDER_WALLET'};
} catch(error) {
  report={schema:'ganesha.runtime.browser-recovery-qa.v1',pass:false,error:String(error),network,failedRequests,consoleErrors,exceptions};
} finally {
  try{await page.call('Page.close');}catch{} page.close(); browser.close();
  try{await fetch(cdp+'/json/close/'+target.id);}catch{}
}
fs.writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({pass:report.pass,reportPath,health:report.health,
  afterCommitLoss:report.afterCommitLoss,beforeCommitLoss:report.beforeCommitLoss,
  viewports:report.viewports,failedRequests:report.network?.failedRequests,console:report.console},null,2));
if(!report.pass)process.exitCode=2;
