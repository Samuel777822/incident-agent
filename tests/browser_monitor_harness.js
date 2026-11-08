const vm = require('vm'), fs = require('fs');
const src = fs.readFileSync(require('path').join(__dirname, '..', 'monitors', 'browser_monitor.js'), 'utf8');
const posts = [];
const listeners = {};
let moCallback = null;
const docListeners = {};
const ctx = {
  console, URL, Blob: class { constructor(p){ this.p = p; } }, setTimeout, setInterval, clearTimeout, JSON, Date, Error, Promise, Math, Number, String, Object, Array, RegExp,
  navigator: { userAgent: 'test-agent' },
  location: { href: 'https://bible.example/isaiah?x=1', pathname: '/isaiah' },
  MutationObserver: class { constructor(cb){ moCallback = cb; } observe(){} },
  document: { visibilityState: 'visible', documentElement: {}, addEventListener(t, fn){ docListeners[t] = fn; } },
  XMLHttpRequest: undefined,
};
ctx.window = ctx;
ctx.addEventListener = (t, fn) => { listeners[t] = fn; };
ctx.AGENT_DAEMON_CONFIG = { ingestUrl: 'https://portal.test/ingest', key: 'adi_k', projectId: 'p1', heartbeatSeconds: 3600 };
const responses = {};
ctx.fetch = function (url, init) {
  url = typeof url === 'string' ? url : url.url;
  if (url.startsWith('https://portal.test/')) { posts.push({ url, body: JSON.parse(init.body) }); return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('{}') }); }
  const r = responses[url.split('?')[0]];
  if (r === 'network') return Promise.reject(new Error('Failed to fetch'));
  return Promise.resolve({ ok: r.status < 400, status: r.status, clone() { return this; }, text: () => Promise.resolve(r.body || '') });
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const errs = () => posts.filter(p => p.body.level === 'ERROR');
const ev = p => { const line = p.body.traceback.split('\n')[0]; return line.startsWith('[evidence] ') ? JSON.parse(line.slice(11)) : null; };
function el(tag, extra) {
  return Object.assign({ tagName: tag, id: '', className: '', innerText: 'Isaiah 1', textContent: 'Isaiah 1', disabled: false,
    getAttribute: () => null, hasAttribute: () => false, closest(sel) { return /video|audio/.test(sel) ? null : this; } }, extra || {});
}
(async () => {
  let failed = 0;
  const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + '  ' + name); if (!cond) failed++; };
  // 1 outside API 404 on any host
  responses['https://bible-api.example/isaiah/1'] = { status: 404, body: '{"error":"chapter not found"}' };
  await ctx.fetch('https://bible-api.example/isaiah/1?key=SECRET'); await sleep(30);
  let e = errs();
  check('failed request on a non-AI host is reported', e.length === 1 && /HTTP 404/.test(e[0].body.message));
  check('evidence line present with kind failed_request, no query string', e[0] && ev(e[0]) && ev(e[0]).kind === 'failed_request' && !JSON.stringify(e[0].body).includes('SECRET'));
  // 2 retired free model on OpenRouter
  responses['https://openrouter.ai/api/v1/chat/completions'] = { status: 404, body: '{"error":{"message":"No endpoints found for meta-llama/llama-3.3-70b-instruct:free."}}' };
  await ctx.fetch('https://openrouter.ai/api/v1/chat/completions', { method: 'POST' }); await sleep(30);
  e = errs();
  check('OpenRouter "No endpoints found" is flagged retired_model', e.length === 2 && ev(e[1]).kind === 'retired_model');
  // 3 noise host ignored
  responses['https://www.google-analytics.com/collect'] = { status: 404, body: '' };
  await ctx.fetch('https://www.google-analytics.com/collect'); await sleep(30);
  check('analytics 404 is ignored', errs().length === 2);
  // 4 network failure
  responses['https://bible-api.example/psalms'] = 'network';
  try { await ctx.fetch('https://bible-api.example/psalms'); } catch (x) {}
  await sleep(30);
  check('network failure is reported', errs().length === 3 && /failed: Failed to fetch/.test(errs()[2].body.message));
  // 5 dead click twice
  const btn = el('BUTTON', { innerText: 'Read chapter', textContent: 'Read chapter' });
  const click = () => docListeners.click({ target: { closest: () => btn }, defaultPrevented: false });
  click(); await sleep(1700); click(); await sleep(1700);
  e = errs();
  check('two dead clicks on the same button are reported', e.length === 4 && ev(e[3]).kind === 'dead_click' && /Read chapter/.test(ev(e[3]).dom));
  // 6 click that changes the page is not dead
  const btn2 = el('BUTTON', { innerText: 'Next', textContent: 'Next' });
  const click2 = () => docListeners.click({ target: { closest: () => btn2 }, defaultPrevented: false });
  click2(); moCallback([{ addedNodes: [] }]); await sleep(1700); click2(); moCallback([{ addedNodes: [] }]); await sleep(1700);
  check('a click that changes the page is not a dead click', errs().length === 4);
  // 7 error text appearing
  moCallback([{ addedNodes: [{ nodeType: 1, tagName: 'DIV', id: 'out', className: 'msg', innerText: 'Failed to load chapter', getAttribute: () => null }] }]); await sleep(30);
  e = errs();
  check('visible error message is reported', e.length === 5 && ev(e[4]).kind === 'ui_error_text');
  // 8 link to another page is navigation, never dead
  const a = el('A', { getAttribute: n => n === 'href' ? '/psalms.html' : null });
  const clickA = () => docListeners.click({ target: { closest: () => a }, defaultPrevented: false });
  clickA(); await sleep(1700); clickA(); await sleep(1700);
  check('normal link is not a dead click', errs().length === 5);
  console.log(failed ? failed + ' FAILED' : 'ALL PASSED');
  process.exit(failed ? 1 : 0);
})();
