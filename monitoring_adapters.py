"""Runtime adapters shipped by the Agent Daemon monitoring installer.

The browser key is intentionally write-only and project-scoped. It can report
errors, but cannot read project data, change settings, or create fixes.
"""

NODE_CJS_SOURCE = r'''/* Agent Daemon Node.js runtime monitor. No third-party dependencies. */
(() => {
  if (globalThis.__agentDaemonMonitorInstalled) return;
  globalThis.__agentDaemonMonitorInstalled = true;
  const fs = require("node:fs");
  const path = require("node:path");
  const https = require("node:https");
  const http = require("node:http");
  let config = {};
  try {
    const p = path.join(process.cwd(), "incident_agent_config.json");
    config = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (_) {}
  const ingestUrl = process.env.INCIDENT_AGENT_INGEST_URL || config.ingest_url || "";
  const ingestKey = process.env.INCIDENT_AGENT_INGEST_KEY || config.ingest_key || "";
  const publicUrl = config.browser_ingest_url || (ingestUrl ? ingestUrl.replace(/\/ingest\/?$/, "/ingest/browser") : "");
  const publicKey = config.browser_ingest_key || "";
  let sent = 0;
  let windowStarted = Date.now();
  let sending = false;

  function allowed() {
    const now = Date.now();
    if (now - windowStarted >= 60000) { windowStarted = now; sent = 0; }
    if (sent >= 30) return false;
    sent += 1;
    return true;
  }
  function post(url, key, payload, publicMode) {
    try {
      const target = new URL(url);
      const body = Buffer.from(JSON.stringify(publicMode ? { project_key: key, event: payload } : payload));
      const transport = target.protocol === "https:" ? https : http;
      const req = transport.request(target, {
        method: "POST",
        timeout: 2500,
        headers: {
          "content-type": "application/json",
          "content-length": body.length,
          ...(publicMode ? {} : { "x-ingest-key": key })
        }
      }, (res) => { res.resume(); });
      req.on("error", () => {});
      req.on("timeout", () => req.destroy());
      req.end(body);
    } catch (_) {}
  }
  function report(message, stack, type) {
    if (sending || !allowed()) return;
    const event = {
      timestamp: new Date().toISOString(),
      level: "ERROR",
      service: "node-runtime",
      message: String(message || "Runtime error").slice(0, 4000),
      traceback: String(stack || "").slice(-12000),
      exception_type: String(type || "Error").slice(0, 200)
    };
    if (!event.traceback) event.traceback = new Error(event.message).stack || event.message;
    sending = true;
    try {
      if (ingestUrl && ingestKey) {
        // Direct HTTPS request, not fetch: avoids instrumenting the monitor's own traffic.
        post(ingestUrl, ingestKey, event, false);
      } else if (publicUrl && publicKey) {
        post(publicUrl, publicKey, event, true);
      }
    } finally { sending = false; }
  }

  // This monitor observes uncaught exceptions without replacing Node's default
  // fatal-error behavior (uncaughtExceptionMonitor does not consume the error).
  process.on("uncaughtExceptionMonitor", (error, origin) => {
    report(error && error.message, error && error.stack, (error && error.name) || origin || "Error");
  });

  // Observe server-side upstream failures without changing the response.
  if (typeof globalThis.fetch === "function") {
    const originalFetch = globalThis.fetch.bind(globalThis);
    globalThis.fetch = async (...args) => {
      const response = await originalFetch(...args);
      if (!sending && (response.status >= 500 || response.status === 429 ||
          (response.status >= 400 && /(^|\.)((openrouter\.ai)|(api\.openai\.com)|(api\.anthropic\.com)|(api\.groq\.com))$/i.test(new URL(response.url || String(args[0]), "http://localhost").hostname)))) {
        const url = response.url || String(args[0] || "upstream");
        const host = (() => { try { return new URL(url).host; } catch (_) { return "upstream"; } })();
        const error = new Error("Upstream request failed: " + response.status + " " + host);
        report(error.message, error.stack, "UpstreamHTTPError");
      }
      return response;
    };
  }
})();
'''

NODE_ESM_SOURCE = r'''/* Agent Daemon Node.js ESM runtime monitor. No third-party dependencies. */
import fs from "node:fs";
import path from "node:path";
import https from "node:https";
import http from "node:http";
if (!globalThis.__agentDaemonMonitorInstalled) {
  globalThis.__agentDaemonMonitorInstalled = true;
  let config = {};
  try { config = JSON.parse(fs.readFileSync(path.join(process.cwd(), "incident_agent_config.json"), "utf8")); } catch {}
  const ingestUrl = process.env.INCIDENT_AGENT_INGEST_URL || config.ingest_url || "";
  const ingestKey = process.env.INCIDENT_AGENT_INGEST_KEY || config.ingest_key || "";
  const publicUrl = config.browser_ingest_url || (ingestUrl ? ingestUrl.replace(/\/ingest\/?$/, "/ingest/browser") : "");
  const publicKey = config.browser_ingest_key || "";
  let sent = 0, windowStarted = Date.now(), sending = false;
  const allowed = () => {
    const now = Date.now();
    if (now - windowStarted >= 60000) { windowStarted = now; sent = 0; }
    if (sent >= 30) return false;
    sent += 1; return true;
  };
  function post(url, key, event, publicMode) {
    try {
      const target = new URL(url), body = Buffer.from(JSON.stringify(publicMode ? { project_key: key, event } : event));
      const transport = target.protocol === "https:" ? https : http;
      const req = transport.request(target, { method:"POST", timeout:2500,
        headers:{ "content-type":"application/json", "content-length":body.length,
          ...(publicMode ? {} : { "x-ingest-key":key }) } }, res => res.resume());
      req.on("error",()=>{}); req.on("timeout",()=>req.destroy()); req.end(body);
    } catch {}
  }
  function report(message, stack, type) {
    if (sending || !allowed()) return;
    const event = { timestamp:new Date().toISOString(), level:"ERROR", service:"node-runtime",
      message:String(message || "Runtime error").slice(0,4000),
      traceback:String(stack || "").slice(-12000), exception_type:String(type || "Error").slice(0,200) };
    if (!event.traceback) event.traceback = new Error(event.message).stack || event.message;
    sending = true;
    try {
      if (ingestUrl && ingestKey) post(ingestUrl,ingestKey,event,false);
      else if (publicUrl && publicKey) post(publicUrl,publicKey,event,true);
    } finally { sending = false; }
  }
  process.on("uncaughtExceptionMonitor", (error, origin) => report(error?.message,error?.stack,error?.name || origin));
  if (typeof globalThis.fetch === "function") {
    const originalFetch = globalThis.fetch.bind(globalThis);
    globalThis.fetch = async (...args) => {
      const response = await originalFetch(...args);
      let host = "";
      try { host = new URL(response.url || String(args[0]), "http://localhost").hostname; } catch {}
      const provider = /(^|\.)((openrouter\.ai)|(api\.openai\.com)|(api\.anthropic\.com)|(api\.groq\.com))$/i.test(host);
      if (!sending && (response.status >= 500 || response.status === 429 || (provider && response.status >= 400))) {
        const error = new Error("Upstream request failed: " + response.status + " " + host);
        report(error.message,error.stack,"UpstreamHTTPError");
      }
      return response;
    };
  }
}
'''

BROWSER_SOURCE = r'''/* Agent Daemon browser monitor. Its project key can only submit error events. */
(() => {
  if (window.__agentDaemonBrowserMonitorInstalled) return;
  window.__agentDaemonBrowserMonitorInstalled = true;
  const key = "__AGENT_DAEMON_BROWSER_KEY__";
  const endpoint = "__AGENT_DAEMON_BROWSER_URL__";
  let sent = 0, started = Date.now();
  function allowed() {
    if (Date.now() - started > 60000) { sent = 0; started = Date.now(); }
    if (sent >= 20) return false;
    sent += 1; return true;
  }
  function report(message, stack, type) {
    if (!key || !endpoint || !allowed()) return;
    const event = {
      timestamp: new Date().toISOString(), level: "ERROR", service: "browser-runtime",
      message: String(message || "Browser error").slice(0, 3000),
      traceback: String(stack || "").slice(-8000),
      exception_type: String(type || "BrowserError").slice(0, 150)
    };
    try {
      const body = JSON.stringify({ project_key: key, event });
      // text/plain + no-cors avoids a CORS preflight; this endpoint is write-only.
      fetch(endpoint, { method:"POST", mode:"no-cors", keepalive:true,
        headers:{ "Content-Type":"text/plain;charset=UTF-8" }, body }).catch(() => {});
    } catch (_) {}
  }
  window.addEventListener("error", event => {
    const target = event.target;
    if (target && target !== window) {
      const url = target.src || target.href || "";
      report("Browser resource failed to load: " + String(url).slice(0,500),
        "Resource load error at " + location.href, "ResourceLoadError");
      return;
    }
    const error = event.error;
    report(event.message || (error && error.message), (error && error.stack) ||
      [event.filename,event.lineno,event.colno].filter(Boolean).join(":"), (error && error.name) || "JavaScriptError");
  }, true);
  window.addEventListener("unhandledrejection", event => {
    const reason = event.reason;
    report(reason && reason.message ? reason.message : String(reason),
      reason && reason.stack ? reason.stack : String(reason), "UnhandledRejection");
  });
  if (typeof window.fetch === "function") {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      if (response.status >= 500 || response.status === 429) {
        let url = ""; try { url = new URL(response.url || String(args[0]), location.href).pathname; } catch {}
        const error = new Error("Browser API request failed: " + response.status + " " + url);
        report(error.message,error.stack,"HTTPError");
      }
      return response;
    };
  }
})();
'''

JAVA_MONITOR_TEMPLATE = r'''/* Agent Daemon Java runtime monitor; standard library only. */
{package_decl}
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.logging.Handler;
import java.util.logging.LogRecord;
import java.util.logging.Logger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class AgentDaemonMonitor {{
  private static volatile boolean installed = false;
  private static String ingestUrl = "", ingestKey = "", browserUrl = "", browserKey = "";
  private AgentDaemonMonitor() {{}}
  public static synchronized void install() {{
    if (installed) return;
    installed = true;
    try {{
      String json = Files.readString(Path.of("incident_agent_config.json"), StandardCharsets.UTF_8);
      ingestUrl = value(json, "ingest_url"); ingestKey = value(json, "ingest_key");
      browserUrl = value(json, "browser_ingest_url"); browserKey = value(json, "browser_ingest_key");
    }} catch (Exception ignored) {{}}
    if (ingestUrl.isEmpty()) ingestUrl = System.getenv().getOrDefault("INCIDENT_AGENT_INGEST_URL", "");
    if (ingestKey.isEmpty()) ingestKey = System.getenv().getOrDefault("INCIDENT_AGENT_INGEST_KEY", "");
    Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {{
      report(error.toString(), stack(error), error.getClass().getSimpleName());
    }});
    Logger.getLogger("").addHandler(new Handler() {{
      @Override public void publish(LogRecord record) {{
        if (record == null || record.getLevel().intValue() < java.util.logging.Level.SEVERE.intValue()) return;
        Throwable thrown = record.getThrown();
        if (thrown != null) report(record.getMessage(), stack(thrown), thrown.getClass().getSimpleName());
      }}
      @Override public void flush() {{}}
      @Override public void close() {{}}
    }});
  }}
  private static String value(String json, String key) {{
    Matcher m = Pattern.compile("\"" + Pattern.quote(key) + "\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"").matcher(json);
    return m.find() ? m.group(1).replace("\\\\\"", "\"").replace("\\\\\\\\", "\\\\") : "";
  }}
  private static String stack(Throwable error) {{
    java.io.StringWriter out = new java.io.StringWriter(); error.printStackTrace(new java.io.PrintWriter(out)); return out.toString();
  }}
  private static void report(String message, String trace, String type) {{
    if (ingestUrl.isEmpty() && browserUrl.isEmpty()) return;
    String json = "{{\"timestamp\":\"" + Instant.now().toString() + "\",\"level\":\"ERROR\",\"service\":\"java-runtime\",\"message\":\"" +
      escape(message) + "\",\"traceback\":\"" + escape(trace) + "\",\"exception_type\":\"" + escape(type) + "\"}}";
    Thread sender = new Thread(() -> send(json), "agent-daemon-reporter"); sender.setDaemon(true); sender.start();
  }}
  private static void send(String event) {{
    try {{
      boolean secret = !ingestUrl.isEmpty() && !ingestKey.isEmpty();
      URL url = new URL(secret ? ingestUrl : browserUrl);
      String body = secret ? event : "{{\"project_key\":\"" + escape(browserKey) + "\",\"event\":" + event + "}}";
      HttpURLConnection conn = (HttpURLConnection) url.openConnection();
      conn.setRequestMethod("POST"); conn.setConnectTimeout(2000); conn.setReadTimeout(2000);
      conn.setDoOutput(true); conn.setRequestProperty("Content-Type", "application/json");
      if (secret) conn.setRequestProperty("X-Ingest-Key", ingestKey);
      try (OutputStream out = conn.getOutputStream()) {{ out.write(body.getBytes(StandardCharsets.UTF_8)); }}
      conn.getResponseCode(); conn.disconnect();
    }} catch (Exception ignored) {{}}
  }}
  private static String escape(String value) {{
    if (value == null) return "";
    return value.replace("\\\\", "\\\\\\\\").replace("\"", "\\\\\"").replace("\r", "\\\\r").replace("\n", "\\\\n").substring(0, Math.min(value.length(), 12000));
  }}
}}
'''
