/* Agent Daemon monitoring client for web pages (plain HTML/JS sites, React, Vite, Next.js client side).
 * Load it as the FIRST script on the page. It:
 *  - checks in with Agent Daemon every 30 seconds while a visitor has the page open,
 *  - reports uncaught errors (window.onerror), unhandled promise rejections, console.error(...) calls and scripts that fail to load,
 *  - reports failed API calls made with fetch or XMLHttpRequest: any 4xx/5xx answer from any site (a Bible API, an AI provider,
 *    your own server), network failures, very slow calls, and any answer that says a model was not found / retired,
 *    together with the server's error message,
 *  - reports "dead clicks" (a button or link that is clicked twice and does nothing) and error messages that appear on the page
 *    ("failed to load", "something went wrong", ...).
 * It never records the screen, keystrokes, form values, cookies or page text. A report holds: the page address (no query
 * string), the failed request address (no query string), the status and the server's error text, and a short label of the
 * clicked element (tag, id, class, button text).
 * The ingest key below can only send heartbeats and error reports for this one project (it cannot read anything),
 * and you can rotate it on your Agent Daemon project page. No dependencies, never throws into your page.
 */
(function () {
  'use strict';
  var w = typeof window !== 'undefined' ? window : null;
  if (!w || w.__agentDaemonMonitor) return;
  var CONFIG = /*__AGENT_DAEMON_CONFIG__*/{ ingestUrl: '', heartbeatUrl: '', key: '', projectId: '', component: '' }/*__END__*/;
  if (w.AGENT_DAEMON_CONFIG) { for (var k in w.AGENT_DAEMON_CONFIG) { CONFIG[k] = w.AGENT_DAEMON_CONFIG[k]; } }
  if (!CONFIG.ingestUrl || !CONFIG.key) { return; }
  if (!CONFIG.heartbeatUrl) { CONFIG.heartbeatUrl = CONFIG.ingestUrl.replace(/\/ingest$/, '/heartbeat'); }
  var VERSION = '3.0.0';
  var HEARTBEAT_SECONDS = Math.max(1, Number(CONFIG.heartbeatSeconds) || 30);
  w.__agentDaemonMonitor = { version: VERSION };

  var AI_HOSTS = ['api.openai.com', 'api.anthropic.com', 'api.groq.com', 'openrouter.ai', 'generativelanguage.googleapis.com',
    'aiplatform.googleapis.com', 'api.mistral.ai', 'api.cohere.com', 'api.cohere.ai', 'api.together.xyz', 'api.deepseek.com',
    'api.x.ai', 'api.perplexity.ai', 'api.fireworks.ai', 'openai.azure.com', 'api-inference.huggingface.co', 'router.huggingface.co'];
  var MODEL_PROBLEM = /model[^\n]{0,120}(not[ _]found|does not exist|decommissioned|deprecated|no longer (supported|available)|retired|invalid|unknown|not supported|is not a valid)|(model_not_found|model_decommissioned|invalid_model|unknown_model)/i;
  var NOISE_HOSTS = ['google-analytics.com', 'googletagmanager.com', 'doubleclick.net', 'facebook.net', 'facebook.com', 'connect.facebook.net', 'sentry.io',
    'hotjar.com', 'clarity.ms', 'segment.io', 'segment.com', 'mixpanel.com', 'amplitude.com', 'fullstory.com', 'logrocket.com', 'datadoghq.com',
    'fonts.googleapis.com', 'fonts.gstatic.com', 'gravatar.com', 'cloudflareinsights.com', 'plausible.io', 'posthog.com'];
  var STATIC_EXT = /\.(png|jpe?g|gif|webp|avif|svg|ico|css|woff2?|ttf|otf|map|mp3|mp4|webm)$/i;
  var ownHost = '';
  try { ownHost = new URL(CONFIG.ingestUrl).host; } catch (e) { /* ignore */ }

  var nativeFetch = w.fetch ? w.fetch.bind(w) : null;
  var nativeWarn = (w.console && w.console.warn) ? w.console.warn.bind(w.console) : function () {};
  var warned = {};
  function say(code, text) { if (warned[code]) return; warned[code] = 1; try { nativeWarn('[agent-daemon] ' + text); } catch (e) { /* ignore */ } }

  // A text/plain body with the key inside is a "simple" CORS request: no preflight, works from any site.
  function send(url, payload, cb) {
    payload.ingest_key = CONFIG.key;
    var body = JSON.stringify(payload);
    try {
      if (!cb && w.navigator && typeof w.navigator.sendBeacon === 'function') {
        if (w.navigator.sendBeacon(url, new Blob([body], { type: 'text/plain' }))) return;
      }
      if (nativeFetch) {
        nativeFetch(url, { method: 'POST', mode: 'cors', credentials: 'omit', keepalive: true, headers: { 'Content-Type': 'text/plain' }, body: body })
          .then(function (r) { if (cb) r.text().then(function (t) { var why = ''; try { why = JSON.parse(t).error || ''; } catch (e) { /* ignore */ } cb(r.ok, r.status, why); }); },
            function (e) { if (cb) cb(false, 0, e && e.message); });
      }
    } catch (e) { if (cb) cb(false, 0, e && e.message); }
  }

  var lastClick = null;
  var recent = [];
  var seen = {};
  var busy = false;
  function report(message, stack, type, context) {
    if (busy) return;
    busy = true;
    try {
      message = String(message || '').slice(0, 4000);
      var now = Date.now();
      recent = recent.filter(function (t) { return now - t < 60000; });
      if (recent.length >= 10 || (seen[message] && now - seen[message] < 60000)) return;
      seen[message] = now;
      recent.push(now);
      context = context || {};
      context.page = String(w.location && w.location.href || '').split('?')[0];
      context.user_agent = w.navigator ? String(w.navigator.userAgent).slice(0, 200) : '';
      var ev = { kind: context.evidence_kind || context.kind || 'js_error', page: context.page };
      if (lastClick && now - lastClick.t < 8000) ev.action = lastClick.desc;
      if (context.url) { ev.request = String(context.method || 'GET').toUpperCase() + ' ' + context.url; }
      if (context.status) ev.status = context.status;
      if (context.response) ev.response = String(context.response).slice(0, 400);
      if (context.dom) ev.dom = context.dom;
      var evidence = '';
      try { evidence = '[evidence] ' + JSON.stringify(ev).slice(0, 1800) + '\n'; } catch (e) { evidence = ''; }
      send(CONFIG.ingestUrl, { project_id: CONFIG.projectId, timestamp: new Date().toISOString(), level: 'ERROR', message: message,
        traceback: evidence + String(stack || '').slice(-10000), exception_type: type || 'Error', monitor: 'browser', component: CONFIG.component,
        context: context });
    } catch (e) { /* ignore */ } finally { busy = false; }
  }

  // ------------------------------------------------------------------------------------------------ errors
  w.addEventListener('error', function (ev) {
    try {
      var t = ev && ev.target;
      if (t && t !== w && (t.tagName === 'SCRIPT' || t.tagName === 'LINK')) {
        report('Failed to load ' + t.tagName.toLowerCase() + ': ' + (t.src || t.href), '', 'ResourceError', { kind: 'resource' });
        return;
      }
      var err = ev && ev.error;
      var msg = (err && err.message) || (ev && ev.message) || 'Script error';
      var where = ev && ev.filename ? ev.filename + ':' + ev.lineno + ':' + ev.colno : '';
      report(((err && err.name) ? err.name + ': ' : '') + msg, (err && err.stack) || where, (err && err.name) || 'Error', { kind: 'onerror', where: where });
    } catch (e) { /* ignore */ }
  }, true);
  w.addEventListener('unhandledrejection', function (ev) {
    try {
      var r = ev && ev.reason;
      var msg = r && r.message ? r.message : (typeof r === 'string' ? r : (function () { try { return JSON.stringify(r); } catch (e) { return String(r); } })());
      report('Unhandled promise rejection: ' + msg, r && r.stack, (r && r.name) || 'UnhandledRejection', { kind: 'unhandledrejection' });
    } catch (e) { /* ignore */ }
  });
  if (w.console && w.console.error) {
    var nativeError = w.console.error;
    w.console.error = function () {
      try {
        var parts = [], stack = '';
        for (var i = 0; i < arguments.length; i++) {
          var a = arguments[i];
          if (a instanceof Error) { parts.push(a.name + ': ' + a.message); stack = stack || a.stack; }
          else if (a && typeof a === 'object') { try { parts.push(JSON.stringify(a).slice(0, 1500)); } catch (e) { parts.push(String(a)); } }
          else parts.push(String(a));
        }
        report(parts.join(' '), stack || (new Error()).stack, 'ConsoleError', { kind: 'console' });
      } catch (e) { /* ignore */ }
      return nativeError.apply(this, arguments);
    };
  }

  // ------------------------------------------------------------------------------------------------ failed API calls
  function hostOf(url) { try { return new URL(url, w.location.href).host; } catch (e) { return ''; } }
  function isAiHost(host) {
    host = String(host || '').toLowerCase().split(':')[0];
    for (var i = 0; i < AI_HOSTS.length; i++) { var h = AI_HOSTS[i]; if (host === h || host.slice(-h.length - 1) === '.' + h || host.slice(-h.length) === h) return true; }
    return false;
  }
  function isNoise(host, url) {
    host = String(host || '').toLowerCase().split(':')[0];
    for (var i = 0; i < NOISE_HOSTS.length; i++) { var h = NOISE_HOSTS[i]; if (host === h || host.slice(-h.length - 1) === '.' + h) return true; }
    return STATIC_EXT.test(String(url).split('?')[0]);
  }
  var netCount = 0;
  function httpProblem(method, url, status, body) {
    var host = hostOf(url);
    if (!host || host === ownHost || isNoise(host, url)) return;
    status = Number(status);
    if (!(status >= 400)) return;
    var text = String(body || '').trim();
    try { var d = JSON.parse(text); var e = d && d.error; var detail = (e && (e.message || (typeof e === 'string' ? e : ''))) || (d && d.message) || ''; if (detail) text = detail + ' | ' + text; } catch (x) { /* not JSON */ }
    var safe = String(url).split('?')[0];
    var modelBad = MODEL_PROBLEM.test(body || '') || (isAiHost(host) && /no endpoints found/i.test(body || ''));
    report(String(method || 'GET').toUpperCase() + ' ' + safe + ' failed with HTTP ' + status + ': ' + text.slice(0, 1500),
      (new Error('request')).stack, 'HTTPError', { kind: 'http', evidence_kind: modelBad ? 'retired_model' : 'failed_request', method: method, url: safe,
        status: status, host: host, response: text });
  }
  if (nativeFetch) {
    w.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && (input.url || input.href)) || String(input);
      var method = (init && init.method) || (input && input.method) || 'GET';
      var started = Date.now();
      netCount++;
      return nativeFetch(input, init).then(function (res) {
        try {
          var took = Date.now() - started;
          if (res && res.status >= 400) res.clone().text().then(function (t) { httpProblem(method, url, res.status, t.slice(0, 2048)); }, function () { httpProblem(method, url, res.status, ''); });
          else if (took > 15000 && hostOf(url) && hostOf(url) !== ownHost && !isNoise(hostOf(url), url)) {
            report(String(method).toUpperCase() + ' ' + String(url).split('?')[0] + ' took ' + Math.round(took / 1000) + ' seconds to answer', '', 'SlowRequest',
              { kind: 'http', evidence_kind: 'failed_request', method: method, url: String(url).split('?')[0], status: res && res.status });
          }
        } catch (e) { /* ignore */ }
        return res;
      }, function (err) {
        try {
          var h = hostOf(url);
          if (h && h !== ownHost && !isNoise(h, url) && !(err && err.name === 'AbortError')) {
            report(String(method).toUpperCase() + ' ' + String(url).split('?')[0] + ' failed: ' + (err && err.message), err && err.stack, 'NetworkError',
              { kind: 'http', evidence_kind: 'failed_request', method: method, url: String(url).split('?')[0], host: h });
          }
        } catch (e) { /* ignore */ }
        throw err;
      });
    };
  }
  if (w.XMLHttpRequest && w.XMLHttpRequest.prototype) {
    var proto = w.XMLHttpRequest.prototype;
    var nativeOpen = proto.open;
    var nativeSend = proto.send;
    proto.open = function (method, url) { try { this.__ad = { method: method, url: String(url) }; } catch (e) { /* ignore */ } return nativeOpen.apply(this, arguments); };
    proto.send = function () {
      var xhr = this;
      netCount++;
      try {
        xhr.addEventListener('loadend', function () {
          try {
            if (!xhr.__ad || xhr.status < 400) return;
            var body = '';
            try { if (!xhr.responseType || xhr.responseType === 'text') body = String(xhr.responseText || '').slice(0, 2048); } catch (e) { /* ignore */ }
            httpProblem(xhr.__ad.method, xhr.__ad.url, xhr.status, body);
          } catch (e) { /* ignore */ }
        });
      } catch (e) { /* ignore */ }
      return nativeSend.apply(this, arguments);
    };
  }

  // ------------------------------------------------------------------------------------------------ dead clicks and visible errors
  var mutations = 0;
  var deadByElement = {};
  var INTERACTIVE = 'a,button,[role="button"],[role="link"],[role="tab"],[onclick],input[type="button"],input[type="submit"],summary';
  var ERROR_TEXT = /(failed to (load|fetch)|could ?n[o']t (load|fetch)|unable to (load|fetch)|error (loading|fetching)|something went wrong|network error|an error (has )?occurred|try again later|service unavailable)/i;
  function describe(el) {
    try {
      var d = String(el.tagName || '').toLowerCase();
      if (el.id) d += '#' + String(el.id).slice(0, 40);
      if (el.className && typeof el.className === 'string') d += '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.').slice(0, 60);
      var label = el.getAttribute && (el.getAttribute('aria-label') || '');
      if (!label && /^(a|button|summary)$/.test(String(el.tagName).toLowerCase())) label = String(el.innerText || el.textContent || '').trim();
      if (label) d += ' "' + label.replace(/\s+/g, ' ').slice(0, 40) + '"';
      return d;
    } catch (e) { return 'element'; }
  }
  function isNavigation(el, ev) {
    var tag = String(el.tagName || '').toLowerCase();
    if (tag === 'a') {
      var href = el.getAttribute('href') || '';
      var tgt = el.getAttribute('target') || '';
      if (el.hasAttribute('download') || tgt === '_blank' || /^(mailto:|tel:|sms:)/i.test(href)) return true;
      if (href && href !== '#' && !/^javascript:/i.test(href)) return !ev.defaultPrevented;
      return false;
    }
    if ((tag === 'button' || tag === 'input') && /submit/i.test(el.getAttribute('type') || (tag === 'button' ? 'submit' : ''))) {
      var form = el.form || (el.closest && el.closest('form'));
      return !!(form && form.getAttribute('action') && !ev.defaultPrevented);
    }
    return false;
  }
  try {
    if (w.MutationObserver && w.document) {
      new w.MutationObserver(function (list) {
        mutations += list.length;
        try {
          for (var i = 0; i < list.length && i < 40; i++) {
            var added = list[i].addedNodes || [];
            for (var j = 0; j < added.length && j < 10; j++) {
              var n = added[j];
              if (!n || n.nodeType !== 1) continue;
              var txt = String(n.innerText || '').trim();
              if (txt && txt.length < 200 && ERROR_TEXT.test(txt)) {
                report('The page shows an error message: ' + txt.replace(/\s+/g, ' ').slice(0, 120), '', 'UIError',
                  { kind: 'ui_error_text', evidence_kind: 'ui_error_text', dom: describe(n) });
                return;
              }
            }
          }
        } catch (e) { /* ignore */ }
      }).observe(w.document.documentElement, { childList: true, subtree: true, attributes: true, characterData: true });
    }
    w.document.addEventListener('click', function (ev) {
      try {
        var el = ev.target && ev.target.closest ? ev.target.closest(INTERACTIVE) : null;
        if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
        if (el.closest && el.closest('video,audio')) return;
        var desc = describe(el);
        lastClick = { t: Date.now(), desc: desc };
        if (isNavigation(el, ev)) return;
        var m0 = mutations, n0 = netCount, u0 = String(w.location.href);
        w.setTimeout(function () {
          try {
            if (mutations !== m0 || netCount !== n0 || String(w.location.href) !== u0) return;
            var now = Date.now(), rec = deadByElement[desc];
            if (rec && now - rec < 15000) {
              deadByElement[desc] = 0;
              report('Dead click: ' + desc + ' was clicked twice and nothing happened', '', 'DeadClick', { kind: 'dead_click', evidence_kind: 'dead_click', dom: desc });
            } else { deadByElement[desc] = now; }
          } catch (e) { /* ignore */ }
        }, 1500);
      } catch (e) { /* ignore */ }
    }, true);
  } catch (e) { /* ignore */ }

  // ------------------------------------------------------------------------------------------------ heartbeat every 30 s
  var beats = 0;
  function beat() {
    if (w.document && w.document.visibilityState === 'hidden' && beats > 0) return;
    send(CONFIG.heartbeatUrl, { project_id: CONFIG.projectId, status: 'ok', timestamp: new Date().toISOString(), monitor: 'browser',
      component: CONFIG.component, version: VERSION, interval: HEARTBEAT_SECONDS, page: String(w.location && w.location.pathname || '') },
    function (ok, status, why) {
      if (ok) { beats++; delete warned.beat; return; }
      say('beat', 'check-in failed (HTTP ' + (status || '-') + ' ' + (why || '') + '). Agent Daemon will mark this site as not checking in.');
    });
  }
  beat();
  w.setInterval(beat, HEARTBEAT_SECONDS * 1000);
  w.__agentDaemonMonitor.report = report;
})();
