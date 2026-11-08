import fs from 'node:fs';

const baseUrl = process.env.GANESHA_A11Y_QA_BASE_URL || 'http://127.0.0.1:8787';
const cdp = process.env.GANESHA_A11Y_QA_CDP || 'http://127.0.0.1:9223';
const reportPath = process.env.GANESHA_A11Y_QA_OUTPUT || 'artifacts/BROWSER_ACCESSIBILITY_QA_20261104_V15_R1.json';
if (fs.existsSync(reportPath)) throw new Error(`refusing to overwrite ${reportPath}`);

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
        const { resolve, reject } = this.pending.get(message.id); this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message)); else resolve(message.result || {});
      } else if (message.method) for (const fn of this.handlers.get(message.method) || []) fn(message.params || {});
    });
  }
  on(method, fn) { if (!this.handlers.has(method)) this.handlers.set(method, []); this.handlers.get(method).push(fn); }
  async call(method, params = {}) {
    await this.ready; const id = ++this.nextId;
    return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  close() { this.ws.close(); }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const waitFor = async (fn, ms = 12000) => {
  const start = Date.now(); while (Date.now() - start < ms) { if (await fn()) return; await sleep(100); }
  throw new Error('browser readiness timeout');
};
const evaluate = async (page, expression) => (await page.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result.value;

let page, browser, target, report;
const consoleErrors = [], exceptions = [], failedRequests = [];
try {
  const created = await fetch(`${cdp}/json/new?about:blank`, { method: 'PUT' });
  if (!created.ok) throw new Error(`Chrome target creation failed: ${created.status}`);
  target = await created.json(); page = new CDP(target.webSocketDebuggerUrl);
  browser = new CDP((await (await fetch(`${cdp}/json/version`)).json()).webSocketDebuggerUrl);
  page.on('Runtime.exceptionThrown', (event) => exceptions.push(event.exceptionDetails?.text || 'exception'));
  page.on('Log.entryAdded', (event) => { if (event.entry?.level === 'error') consoleErrors.push(event.entry.text); });
  page.on('Network.loadingFailed', (event) => failedRequests.push({ error: event.errorText, url: event.requestId }));
  await page.call('Page.enable'); await page.call('Runtime.enable'); await page.call('Log.enable'); await page.call('Network.enable');
  await page.call('Page.navigate', { url: baseUrl });
  await waitFor(async () => evaluate(page, `document.readyState === 'complete' && !!document.querySelector('#board img')`));
  await page.call('Emulation.setDeviceMetricsOverride', { width: 320, height: 900, deviceScaleFactor: 2, mobile: true });
  await sleep(500);
  const metrics = await evaluate(page, `(() => {
    const imgs=[...document.images].map(x=>({alt:x.alt,complete:x.complete,naturalWidth:x.naturalWidth,src:x.getAttribute('src')}));
    const controls=[...document.querySelectorAll('button,a[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')].map(x=>({tag:x.tagName,id:x.id,role:x.getAttribute('role'),name:(x.getAttribute('aria-label')||x.getAttribute('aria-labelledby')||[...(x.labels||[])].map(l=>l.innerText).join(' ')||x.innerText||x.getAttribute('title')||'').trim(),disabled:!!x.disabled,tabIndex:x.tabIndex,rect:(()=>{const r=x.getBoundingClientRect();return {width:r.width,height:r.height}})()}));
    const unnamed=controls.filter(x=>!x.name);
    const undersized=controls.filter(x=>x.rect.width>0&&x.rect.height>0&&(x.rect.width<24||x.rect.height<24));
    const demoSpin=document.getElementById('demo-spin-button');
    return {viewport:{width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,horizontalOverflow:document.documentElement.scrollWidth>innerWidth},boardCells:document.querySelectorAll('#board .symbol').length,images:imgs,brokenImages:imgs.filter(x=>!x.complete||x.naturalWidth===0),controls,unnamedControls:unnamed,undersizedTargets:undersized,financialControlsDisabled:['bet-down','bet-up'].every(id=>document.getElementById(id)?.disabled),bonusControlsDisabled:[...document.querySelectorAll('[data-buy],.buy-button')].every(x=>x.disabled),demoSpinNonFinancialLabel:demoSpin?.getAttribute('aria-label')==='Run fixed non-financial demo spin'&&demoSpin?.innerText.includes('FIXED BOARD · NO WAGER'),skipLink:!!document.querySelector('.skip-link[href="#game-preview"]')};
  })()`);
  await page.call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await page.call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  const skipFocus = await evaluate(page, `({active:document.activeElement?.className,outline:getComputedStyle(document.activeElement).outlineStyle,width:getComputedStyle(document.activeElement).outlineWidth})`);
  report = {
    schema: 'ganesha-browser-accessibility-reflow-qa.v1',
    classification: 'LOCAL_BROWSER_REFLOW_AND_DOM_SEMANTICS_CHECK_NOT_FULL_WCAG_AA_OR_PHYSICAL_DEVICE_CERTIFICATION',
    browser: (await (await fetch(`${cdp}/json/version`)).json()).Browser,
    viewport_mode: '320 CSS-pixel viewport at deviceScaleFactor 2; narrow reflow proxy for 200% zoom, not a literal desktop browser-zoom test',
    metrics, skipFocus,
    consoleErrors, exceptions, failedRequests,
    pass: !metrics.viewport.horizontalOverflow && metrics.boardCells === 15 && metrics.brokenImages.length === 0
      && metrics.unnamedControls.length === 0 && metrics.undersizedTargets.length === 0
      && metrics.financialControlsDisabled && metrics.bonusControlsDisabled && metrics.demoSpinNonFinancialLabel && metrics.skipLink
      && skipFocus.active === 'skip-link' && skipFocus.outline !== 'none' && parseFloat(skipFocus.width) >= 2
      && !consoleErrors.length && !exceptions.length && !failedRequests.length,
    limitations: ['No screen-reader device/AT session was available','No physical iOS/Android browser was tested','320 CSS px is a reflow proxy, not a literal desktop 200% zoom run','Color contrast audit remains limited to existing selected-pair automated tests']
  };
} catch (error) {
  report = { schema: 'ganesha-browser-accessibility-reflow-qa.v1', pass: false, error: String(error), consoleErrors, exceptions, failedRequests };
} finally {
  try { if (page) await page.call('Page.close'); } catch {}
  if (page) page.close(); if (browser) browser.close();
  try { if (target) await fetch(`${cdp}/json/close/${target.id}`); } catch {}
}
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
console.log(JSON.stringify({ pass: report.pass, reportPath, viewport: report.metrics?.viewport, boardCells: report.metrics?.boardCells, brokenImages: report.metrics?.brokenImages, unnamedControls: report.metrics?.unnamedControls, undersizedTargets: report.metrics?.undersizedTargets, skipFocus: report.skipFocus, consoleErrors, exceptions, failedRequests, limitations: report.limitations }, null, 2));
if (!report.pass) process.exitCode = 2;
