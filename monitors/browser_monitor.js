/* Agent Daemon monitoring client for web pages (plain HTML/JS sites, React, Vite, Next.js client side).
 * Load it as the FIRST script on the page. It:
 *  - checks in with Agent Daemon every 30 seconds while a visitor has the page open,
 *  - reports uncaught errors (window.onerror), unhandled promise rejections, console.error(...) calls and scripts that fail to load,
 *  - reports failed API calls made with fetch or XMLHttpRequest: any 5xx answer, any 4xx answer from an AI provider
 *    (OpenAI, Anthropic, Groq, OpenRouter, Gemini, ...) and any answer that says a model was not found / retired,
 *    together with the provider's error message.
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
  var VERSION = '2.0.0';
  var HEARTBEAT_SECONDS = Math.max(1, Number(CONFIG.heartbeatSeconds) || 30);
  w.__agentDaemonMonitor = { version: VERSION };

  var AI_HOSTS = ['api.openai.com', 'api.anthropic.com', 'api.groq.com', 'openrouter.ai', 'generativelanguage.googleapis.com',
    'aiplatform.googleapis.com', 'api.mistral.ai', 'api.cohere.com', 'api.cohere.ai', 'api.together.xyz', 'api.deepseek.com',
    'api.x.ai', 'api.perplexity.ai', 'api.fireworks.ai', 'openai.azure.com', 'api-inference.huggingface.co', 'router.huggingface.co'];
  var MODEL_PROBLEM = /model[^\n]{0,120}(not[ _]found|does not exist|decommissioned|deprecated|no longer (supported|available)|retired|invalid|unknown|not supported|is not a valid)|(model_not_found|model_decommissioned|invalid_model|unknown_model)/i;
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
      send(CONFIG.ingestUrl, { project_id: CONFIG.projectId, timestamp: new Date().toISOString(), level: 'ERROR', message: message,
        traceback: String(stack || '').slice(-12000), exception_type: type || 'Error', monitor: 'browser', component: CONFIG.component,
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
  function httpProblem(method, url, status, body) {
    var host = hostOf(url);
    if (!host || host === ownHost) return;
    status = Number(status);
    if (!(status >= 400)) return;
    if (!(status >= 500 || isAiHost(host) || MODEL_PROBLEM.test(body || ''))) return;
    var text = String(body || '').trim();
    try { var d = JSON.parse(text); var e = d && d.error; var detail = (e && (e.message || (typeof e === 'string' ? e : ''))) || (d && d.message) || ''; if (detail) text = detail + ' | ' + text; } catch (x) { /* not JSON */ }
    var safe = String(url).split('?')[0];
    report(String(method || 'GET').toUpperCase() + ' ' + safe + ' failed with HTTP ' + status + ': ' + text.slice(0, 1500),
      (new Error('request')).stack, 'HTTPError', { kind: 'http', method: method, url: safe, status: status, host: host });
  }
  if (nativeFetch) {
    w.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && (input.url || input.href)) || String(input);
      var method = (init && init.method) || (input && input.method) || 'GET';
      return nativeFetch(input, init).then(function (res) {
        try { if (res && res.status >= 400) res.clone().text().then(function (t) { httpProblem(method, url, res.status, t.slice(0, 2048)); }, function () { httpProblem(method, url, res.status, ''); }); } catch (e) { /* ignore */ }
        return res;
      }, function (err) {
        try { var h = hostOf(url); if (h && h !== ownHost && isAiHost(h)) report(String(method).toUpperCase() + ' ' + String(url).split('?')[0] + ' failed: ' + (err && err.message), err && err.stack, 'NetworkError', { kind: 'http' }); } catch (e) { /* ignore */ }
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
