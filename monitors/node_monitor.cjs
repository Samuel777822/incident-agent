/* Agent Daemon monitoring client for Node.js (Express, Next.js server, plain Node). Loading this file starts monitoring.
 *
 *  - checks in with Agent Daemon every 30 seconds (project id, status, timestamp),
 *  - reports uncaught exceptions and unhandled promise rejections WITHOUT changing how your app crashes,
 *  - reports console.error(...) calls,
 *  - reports failed outgoing API calls made with fetch, http or https (axios, the OpenAI / Anthropic SDKs, ...):
 *    any 5xx answer, any 4xx answer from an AI provider, or any answer that says a model was not found / retired,
 *    together with the provider's error message.
 *
 * Configuration: INCIDENT_AGENT_INGEST_URL and INCIDENT_AGENT_INGEST_KEY, or incident-agent-config.json next to this
 * file (Agent Daemon writes it for you). The key can only send heartbeats and error reports for this one project.
 * No dependencies. Never throws into your app. Problems are printed once to stderr with the prefix "[agent-daemon]".
 */
'use strict';
(function () {
  if (global.__agentDaemonMonitor) return;
  if (/^(1|true|yes)$/i.test(process.env.AGENT_DAEMON_DISABLE || '')) return;
  var fs = require('fs');
  var path = require('path');
  var http = require('http');
  var https = require('https');
  var childProcess = require('child_process');

  var VERSION = '2.0.0';
  var HEARTBEAT_SECONDS = Math.max(1, Math.min(3600, parseInt(process.env.AGENT_DAEMON_HEARTBEAT_SECONDS || '30', 10) || 30));
  var AI_HOSTS = ['api.openai.com', 'api.anthropic.com', 'api.groq.com', 'openrouter.ai', 'generativelanguage.googleapis.com',
    'aiplatform.googleapis.com', 'api.mistral.ai', 'api.cohere.com', 'api.cohere.ai', 'api.together.xyz', 'api.deepseek.com',
    'api.x.ai', 'api.perplexity.ai', 'api.fireworks.ai', 'openai.azure.com', 'api-inference.huggingface.co', 'router.huggingface.co'];
  var MODEL_PROBLEM = /model[^\n]{0,120}(not[ _]found|does not exist|decommissioned|deprecated|no longer (supported|available)|retired|invalid|unknown|not supported|is not a valid)|(model_not_found|model_decommissioned|invalid_model|unknown_model)/i;

  function readConfig() {
    var url = (process.env.INCIDENT_AGENT_INGEST_URL || '').trim();
    var key = (process.env.INCIDENT_AGENT_INGEST_KEY || '').trim();
    var extra = {};
    var places = [path.join(__dirname, 'incident-agent-config.json'), path.join(process.cwd(), 'incident-agent-config.json')];
    for (var i = 0; i < places.length; i++) {
      try {
        extra = JSON.parse(fs.readFileSync(places[i], 'utf8')) || {};
        url = url || String(extra.ingest_url || '').trim();
        key = key || String(extra.ingest_key || '').trim();
        break;
      } catch (e) { /* try the next place */ }
    }
    var beat = extra.heartbeat_url || (/\/ingest$/.test(url) ? url.replace(/\/ingest$/, '/heartbeat') : url.replace(/\/[^/]*$/, '/heartbeat'));
    return { url: url, key: key, heartbeat: beat, projectId: extra.project_id || '', component: extra.component || '' };
  }

  var cfg = readConfig();
  var warned = {};
  function say(code, text) {
    if (warned[code]) return;
    warned[code] = true;
    try { process.stderr.write('[agent-daemon] ' + text + '\n'); } catch (e) { /* ignore */ }
  }
  if (!cfg.url || !cfg.key) {
    say('no-config', 'monitoring is OFF: no incident-agent-config.json and no INCIDENT_AGENT_INGEST_URL / INCIDENT_AGENT_INGEST_KEY. ' +
      'Re-install monitoring from your Agent Daemon project page.');
    return;
  }
  global.__agentDaemonMonitor = { version: VERSION };

  var ownHost = '';
  try { ownHost = new URL(cfg.url).host; } catch (e) { /* ignore */ }
  var inOwnCall = 0;
  var stats = { beatsOk: 0, errorsSent: 0 };

  // ------------------------------------------------------------------------------------------------ transport
  var originalRequest = { http: http.request, https: https.request };
  function post(target, payload, done) {
    var body = JSON.stringify(payload);
    var u;
    try { u = new URL(target); } catch (e) { if (done) done(false, 0, 'bad url'); return; }
    var mod = u.protocol === 'http:' ? 'http' : 'https';
    inOwnCall++;
    try {
      var req = originalRequest[mod].call(mod === 'http' ? http : https, {
        method: 'POST', hostname: u.hostname, port: u.port || undefined, path: u.pathname + u.search,
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body), 'X-Ingest-Key': cfg.key,
          'User-Agent': 'agent-daemon-node/' + VERSION },
        timeout: 5000
      }, function (res) {
        var chunks = '';
        res.setEncoding('utf8');
        res.on('data', function (c) { if (chunks.length < 500) chunks += c; });
        res.on('end', function () {
          var reason = '';
          try { reason = JSON.parse(chunks || '{}').error || ''; } catch (e) { /* ignore */ }
          if (done) done(res.statusCode < 300, res.statusCode, reason);
        });
      });
      req.on('timeout', function () { req.destroy(new Error('timeout')); });
      req.on('error', function (err) { if (done) done(false, 0, err && err.code || 'network error'); });
      if (typeof req.setNoDelay === 'function') req.setNoDelay(true);
      req.end(body);
      if (req.socket && req.socket.unref) req.socket.unref();
      req.on('socket', function (s) { if (s && s.unref) s.unref(); });
    } catch (e) {
      if (done) done(false, 0, e && e.message);
    } finally {
      inOwnCall--;
    }
  }

  var recent = [];
  var seen = {};
  function allowed(message) {
    var now = Date.now();
    recent = recent.filter(function (t) { return now - t < 60000; });
    if (recent.length >= 30) return false;
    if (seen[message] && now - seen[message] < 10000) return false;
    seen[message] = now;
    recent.push(now);
    return true;
  }

  var reporting = false;
  function report(message, stack, level, type, context) {
    if (reporting) return false;
    reporting = true;
    try {
      message = String(message || '').slice(0, 4000);
      if (!allowed(message + String(stack || '').slice(-200))) return false;
      post(cfg.url, {
        project_id: cfg.projectId, timestamp: new Date().toISOString(), level: level || 'ERROR', message: message,
        traceback: String(stack || '').slice(-12000), exception_type: type || 'Error', monitor: 'node', component: cfg.component,
        context: context || {}
      }, function (ok, status, reason) {
        if (ok) stats.errorsSent++;
        else say('ingest-' + status, 'could not report an error to Agent Daemon (HTTP ' + (status || 'no connection') + ' ' + reason + ').');
      });
      return true;
    } catch (e) {
      return false;
    } finally {
      reporting = false;
    }
  }

  function reportSync(message, stack, type, origin) {
    // The process is about to die: send synchronously from a tiny child process so the report is not lost.
    try {
      var payload = JSON.stringify({ project_id: cfg.projectId, timestamp: new Date().toISOString(), level: 'CRITICAL',
        message: String(message || '').slice(0, 4000), traceback: String(stack || '').slice(-12000), exception_type: type || 'Error',
        monitor: 'node', component: cfg.component, context: { kind: origin || 'uncaught' } });
      var script = "const u=new URL(process.argv[1]);const m=require(u.protocol==='http:'?'http':'https');let b='';" +
        "process.stdin.on('data',d=>b+=d).on('end',()=>{const r=m.request({method:'POST',hostname:u.hostname,port:u.port||undefined," +
        "path:u.pathname,headers:{'Content-Type':'application/json','X-Ingest-Key':process.argv[2]},timeout:4000},res=>{res.resume();res.on('end',()=>process.exit(0))});" +
        "r.on('error',()=>process.exit(1));r.end(b);});";
      childProcess.spawnSync(process.execPath, ['-e', script, cfg.url, cfg.key], { input: payload, timeout: 6000, stdio: ['pipe', 'ignore', 'ignore'] });
    } catch (e) { /* ignore */ }
  }

  // ------------------------------------------------------------------------------------------------ crashes (behaviour unchanged)
  process.on('uncaughtExceptionMonitor', function (err, origin) {
    try {
      var e = err instanceof Error ? err : new Error(String(err));
      reportSync(e.message || String(err), e.stack || '', e.name || 'Error', origin === 'unhandledRejection' ? 'unhandledRejection' : 'uncaught');
    } catch (x) { /* ignore */ }
  });
  // Node < 15 (or --unhandled-rejections=warn) only warns about unhandled rejections: report those too.
  process.on('warning', function (w) {
    if (w && /Unhandled promise rejection/i.test(String(w.message))) report(w.message, w.stack, 'ERROR', 'UnhandledRejection', { kind: 'unhandledRejection' });
  });

  // ------------------------------------------------------------------------------------------------ console.error
  var originalError = console.error;
  console.error = function () {
    try {
      var parts = [];
      var stack = '';
      for (var i = 0; i < arguments.length; i++) {
        var a = arguments[i];
        if (a instanceof Error) { parts.push(a.name + ': ' + a.message); stack = stack || a.stack; }
        else if (typeof a === 'object') { try { parts.push(JSON.stringify(a).slice(0, 1500)); } catch (e) { parts.push(String(a)); } }
        else parts.push(String(a));
      }
      if (!inOwnCall) report(parts.join(' '), stack || new Error().stack, 'ERROR', 'ConsoleError', { kind: 'console' });
    } catch (e) { /* ignore */ }
    return originalError.apply(console, arguments);
  };

  // ------------------------------------------------------------------------------------------------ outgoing HTTP
  function isAiHost(host) {
    host = String(host || '').toLowerCase();
    return AI_HOSTS.some(function (h) { return host === h || host.slice(-h.length - 1) === '.' + h || host.slice(-h.length) === h; });
  }
  function shouldReport(status, host, body) {
    status = Number(status);
    if (!(status >= 400)) return false;
    if (status >= 500 || isAiHost(host)) return true;
    return MODEL_PROBLEM.test(body || '');
  }
  function httpProblem(method, url, status, body) {
    var host = '', hostPort = '';
    try { var parsed = new URL(url); host = parsed.hostname; hostPort = parsed.host; } catch (e) { /* ignore */ }
    if (hostPort === ownHost || !shouldReport(status, host, body)) return;
    var text = String(body || '').trim();
    try {
      var data = JSON.parse(text);
      var err = data && data.error;
      var detail = (err && (err.message || (typeof err === 'string' ? err : ''))) || (data && data.message) || '';
      if (detail) text = detail + ' | ' + text;
    } catch (e) { /* not JSON */ }
    var safe = String(url).split('?')[0];
    report(String(method || 'GET').toUpperCase() + ' ' + safe + ' failed with HTTP ' + status + ': ' + text.slice(0, 1500),
      new Error('outgoing request').stack, 'ERROR', 'HTTPError', { kind: 'http', method: method, url: safe, status: Number(status), host: host });
  }

  if (typeof globalThis.fetch === 'function') {
    var originalFetch = globalThis.fetch;
    globalThis.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && (input.url || input.href)) || String(input);
      var method = (init && init.method) || (input && input.method) || 'GET';
      var own = false;
      try { own = new URL(url).host === ownHost; } catch (e) { /* relative */ }
      return originalFetch.apply(this, arguments).then(function (res) {
        try {
          if (!own && res && res.status >= 400) {
            res.clone().text().then(function (t) { httpProblem(method, url, res.status, t.slice(0, 2048)); }, function () { httpProblem(method, url, res.status, ''); });
          }
        } catch (e) { /* ignore */ }
        return res;
      }, function (err) {
        try {
          var host = new URL(url).hostname;
          if (!own && isAiHost(host)) report(String(method).toUpperCase() + ' ' + url.split('?')[0] + ' failed: ' + (err && err.message), err && err.stack, 'ERROR', 'NetworkError', { kind: 'http', url: url.split('?')[0] });
        } catch (e) { /* ignore */ }
        throw err;
      });
    };
  }

  function wrapRequest(mod, name, scheme) {
    var original = mod[name];
    mod[name] = function () {
      var req = original.apply(this, arguments);
      try {
        if (inOwnCall) return req;
        var opts = arguments[0];
        var url = typeof opts === 'string' ? opts : (opts instanceof URL ? opts.href : '');
        if (!url && opts && typeof opts === 'object') url = scheme + '://' + (opts.hostname || opts.host || 'localhost') + (opts.port ? ':' + opts.port : '') + (opts.path || '/');
        var method = (opts && opts.method) || (arguments[1] && arguments[1].method) || 'GET';
        req.on('response', function (res) {
          try {
            if (res.statusCode < 400) return;
            var collected = '';
            var sent = false;
            var finish = function () { if (sent) return; sent = true; httpProblem(method, url, res.statusCode, collected); };
            var emit = res.emit;
            res.emit = function (ev, chunk) {
              try {
                if (ev === 'data' && collected.length < 2048) collected += Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
                if (ev === 'end') finish();
              } catch (e) { /* ignore */ }
              return emit.apply(this, arguments);
            };
            var t = setTimeout(finish, 5000);
            if (t.unref) t.unref();
          } catch (e) { /* ignore */ }
        });
      } catch (e) { /* ignore */ }
      return req;
    };
  }
  wrapRequest(http, 'request', 'http');
  wrapRequest(https, 'request', 'https');
  wrapRequest(http, 'get', 'http');
  wrapRequest(https, 'get', 'https');

  // ------------------------------------------------------------------------------------------------ heartbeat every 30 s
  function beat() {
    post(cfg.heartbeat, {
      project_id: cfg.projectId, status: 'ok', timestamp: new Date().toISOString(), monitor: 'node', component: cfg.component,
      version: VERSION, runtime: 'node ' + process.version, interval: HEARTBEAT_SECONDS, errors_sent: stats.errorsSent
    }, function (ok, status, reason) {
      if (ok) {
        if (!stats.beatsOk) say('connected', 'monitor connected: first check-in accepted (every ' + HEARTBEAT_SECONDS + 's from now on).');
        stats.beatsOk++;
        delete warned['beat-fail'];
      } else {
        say('beat-fail', 'check-in failed (HTTP ' + (status || '-') + ' ' + reason + '): ' +
          (status === 401 ? 'the key was rejected. Re-install monitoring from your project page.' : 'will retry automatically.'));
      }
    });
  }
  beat();
  var timer = setInterval(beat, HEARTBEAT_SECONDS * 1000);
  if (timer.unref) timer.unref();
  module.exports = { report: report, heartbeat: beat, version: VERSION };
})();
