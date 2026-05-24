import { execFile, spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import tls from "node:tls";
import { promisify } from "node:util";
import { config } from "../config.js";
import { db } from "../db.js";

const execFileAsync = promisify(execFile);
const supportedProtocols = new Set(["vless", "vmess", "trojan", "ss"]);

type XraySummary = {
  runId: number;
  checkedNodes: number;
  realPassedNodes: number;
  failedNodes: number;
  skippedNodes: number;
  avgRealLatencyMs: number | null;
  configured: boolean;
};

type NodeRow = {
  id: number;
  protocol: string;
  content: string;
};

type ProbeResult = {
  ok: boolean;
  latencyMs: number | null;
  reason: string | null;
};

type VmessConfig = {
  v?: string;
  ps?: string;
  add?: string;
  port?: string | number;
  id?: string;
  aid?: string | number;
  scy?: string;
  net?: string;
  type?: string;
  host?: string;
  path?: string;
  tls?: string;
  sni?: string;
};

let activeRun: Promise<XraySummary> | null = null;

export async function runXrayRealTests(options?: { limit?: number }) {
  if (activeRun) return activeRun;
  activeRun = runXrayRealTestsInternal(options).finally(() => {
    activeRun = null;
  });
  return activeRun;
}

async function runXrayRealTestsInternal(options?: { limit?: number }): Promise<XraySummary> {
  const limit = Math.max(1, Math.min(options?.limit ?? 50, 200));
  const startedAt = new Date().toISOString();
  const runResult = db
    .prepare("INSERT INTO test_runs (status, started_at, test_method) VALUES ('running', ?, 'xray-core')")
    .run(startedAt);
  const runId = Number(runResult.lastInsertRowid);

  const configured = await isXrayConfigured();
  const nodes = db
    .prepare(
      `SELECT id, protocol, content
       FROM nodes
       WHERE status = 'test_passed'
       ORDER BY COALESCE(real_tested_at, last_tested_at, collected_at) ASC
       LIMIT ?`
    )
    .all(limit) as NodeRow[];

  let realPassedNodes = 0;
  let failedNodes = 0;
  let skippedNodes = 0;
  const latencies: number[] = [];

  const binaryProbe = configured ? await probeXrayBinary() : { ok: false, reason: "xray_not_configured" };

  await runWithConcurrency(nodes, config.XRAY_REAL_TEST_CONCURRENCY, async (node) => {
    if (!configured) {
      skippedNodes += 1;
      recordXrayResult(runId, node.id, "xray_not_configured", null, "xray_not_configured");
      return;
    }
    if (!binaryProbe.ok) {
      failedNodes += 1;
      recordXrayResult(runId, node.id, "real_failed", null, binaryProbe.reason ?? "xray_probe_failed");
      return;
    }
    if (!supportedProtocols.has(node.protocol)) {
      skippedNodes += 1;
      recordXrayResult(runId, node.id, "xray_unsupported_protocol", null, "unsupported_protocol");
      return;
    }

    const result = await testNodeWithXray(node);
    if (result.ok && result.latencyMs !== null) {
      realPassedNodes += 1;
      latencies.push(result.latencyMs);
      recordXrayResult(runId, node.id, "real_passed", result.latencyMs, null);
      return;
    }

    failedNodes += 1;
    recordXrayResult(runId, node.id, "real_failed", null, result.reason ?? "proxy_failed");
  });

  const summary: XraySummary = {
    runId,
    checkedNodes: nodes.length,
    realPassedNodes,
    failedNodes,
    skippedNodes,
    avgRealLatencyMs: latencies.length ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length) : null,
    configured
  };

  db.prepare(
    `UPDATE test_runs
     SET status = 'completed', finished_at = ?, tested_nodes = ?, passed_nodes = ?, failed_nodes = ?,
         removed_nodes = 0, avg_latency_ms = ?, summary_json = ?
     WHERE id = ?`
  ).run(new Date().toISOString(), nodes.length, realPassedNodes, failedNodes, summary.avgRealLatencyMs, JSON.stringify(summary), runId);

  return summary;
}

async function isXrayConfigured() {
  if (!config.XRAY_REAL_TEST_ENABLED || !config.XRAY_CORE_PATH) return false;
  return fs.existsSync(config.XRAY_CORE_PATH);
}

async function probeXrayBinary() {
  try {
    await execFileAsync(config.XRAY_CORE_PATH, ["version"], {
      timeout: config.XRAY_REAL_TEST_TIMEOUT_MS,
      windowsHide: true
    });
    return { ok: true as const, reason: null };
  } catch {
    return { ok: false as const, reason: "xray_probe_failed" };
  }
}

async function testNodeWithXray(node: NodeRow): Promise<ProbeResult> {
  const port = randomLocalPort();
  const tempDir = await mkdtemp(path.join(os.tmpdir(), "pna-xray-"));
  const configPath = path.join(tempDir, "config.json");
  let child: ChildProcess | null = null;

  try {
    const xrayConfig = buildXrayConfig(node, port);
    await writeFile(configPath, JSON.stringify(xrayConfig), "utf8");

    child = spawn(config.XRAY_CORE_PATH, ["run", "-config", configPath], {
      stdio: "ignore",
      windowsHide: true
    });

    const started = await waitForLocalPort(port, child, Math.min(3000, config.XRAY_REAL_TEST_TIMEOUT_MS));
    if (!started) return { ok: false, latencyMs: null, reason: "xray_start_failed" };

    return await requestThroughLocalProxy(port, config.XRAY_TEST_URL, config.XRAY_REAL_TEST_TIMEOUT_MS);
  } catch (error) {
    return { ok: false, latencyMs: null, reason: error instanceof Error ? normalizeFailureReason(error.message) : "invalid_config" };
  } finally {
    await stopProcess(child);
    await rm(tempDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

function buildXrayConfig(node: NodeRow, localPort: number) {
  return {
    log: { loglevel: "warning" },
    inbounds: [
      {
        tag: "local-http",
        listen: "127.0.0.1",
        port: localPort,
        protocol: "http",
        settings: { timeout: Math.ceil(config.XRAY_REAL_TEST_TIMEOUT_SECONDS) }
      }
    ],
    outbounds: [buildOutbound(node)]
  };
}

function buildOutbound(node: NodeRow) {
  if (node.protocol === "vmess") return buildVmessOutbound(node.content);
  if (node.protocol === "vless") return buildVlessOutbound(node.content);
  if (node.protocol === "trojan") return buildTrojanOutbound(node.content);
  if (node.protocol === "ss") return buildShadowsocksOutbound(node.content);
  throw new Error("unsupported_protocol");
}

function buildVlessOutbound(content: string) {
  const url = new URL(content);
  const port = Number(url.port);
  const id = decodeURIComponent(url.username);
  if (!url.hostname || !port || !id) throw new Error("invalid_config");
  return stripUndefined({
    protocol: "vless",
    settings: {
      vnext: [
        {
          address: stripBrackets(url.hostname),
          port,
          users: [
            {
              id,
              encryption: url.searchParams.get("encryption") || "none",
              flow: url.searchParams.get("flow") || undefined
            }
          ]
        }
      ]
    },
    streamSettings: streamSettingsFromUrl(url)
  });
}

function buildTrojanOutbound(content: string) {
  const url = new URL(content);
  const port = Number(url.port);
  const password = decodeURIComponent(url.username);
  if (!url.hostname || !port || !password) throw new Error("invalid_config");
  return stripUndefined({
    protocol: "trojan",
    settings: {
      servers: [{ address: stripBrackets(url.hostname), port, password }]
    },
    streamSettings: streamSettingsFromUrl(url)
  });
}

function buildVmessOutbound(content: string) {
  const payload = content.replace(/^vmess:\/\//i, "");
  const vmess = JSON.parse(base64Decode(payload)) as VmessConfig;
  const port = Number(vmess.port);
  if (!vmess.add || !port || !vmess.id) throw new Error("invalid_config");
  return stripUndefined({
    protocol: "vmess",
    settings: {
      vnext: [
        {
          address: vmess.add,
          port,
          users: [
            {
              id: vmess.id,
              alterId: Number(vmess.aid ?? 0),
              security: vmess.scy || "auto"
            }
          ]
        }
      ]
    },
    streamSettings: streamSettingsFromVmess(vmess)
  });
}

function buildShadowsocksOutbound(content: string) {
  const parsed = parseShadowsocks(content);
  if (!parsed) throw new Error("invalid_config");
  return {
    protocol: "shadowsocks",
    settings: {
      servers: [
        {
          address: parsed.address,
          port: parsed.port,
          method: parsed.method,
          password: parsed.password
        }
      ]
    }
  };
}

function streamSettingsFromUrl(url: URL) {
  const network = normalizeNetwork(url.searchParams.get("type") || url.searchParams.get("network") || "tcp");
  const security = normalizeSecurity(url.searchParams.get("security") || "none");
  const host = stripBrackets(url.hostname);
  return stripUndefined({
    network,
    security,
    tlsSettings:
      security === "tls"
        ? { serverName: url.searchParams.get("sni") || url.searchParams.get("peer") || url.searchParams.get("host") || host }
        : undefined,
    realitySettings:
      security === "reality"
        ? {
            serverName: url.searchParams.get("sni") || host,
            publicKey: url.searchParams.get("pbk") || url.searchParams.get("publicKey") || undefined,
            shortId: url.searchParams.get("sid") || url.searchParams.get("shortId") || undefined,
            fingerprint: url.searchParams.get("fp") || "chrome"
          }
        : undefined,
    wsSettings:
      network === "ws"
        ? {
            path: url.searchParams.get("path") || "/",
            headers: { Host: url.searchParams.get("host") || url.searchParams.get("sni") || host }
          }
        : undefined,
    grpcSettings: network === "grpc" ? { serviceName: url.searchParams.get("serviceName") || url.searchParams.get("service") || "" } : undefined
  });
}

function streamSettingsFromVmess(vmess: VmessConfig) {
  const network = normalizeNetwork(vmess.net || "tcp");
  const security = normalizeSecurity(vmess.tls || "none");
  return stripUndefined({
    network,
    security,
    tlsSettings: security === "tls" ? { serverName: vmess.sni || vmess.host || vmess.add } : undefined,
    wsSettings:
      network === "ws"
        ? {
            path: vmess.path || "/",
            headers: vmess.host ? { Host: vmess.host } : undefined
          }
        : undefined,
    grpcSettings: network === "grpc" ? { serviceName: vmess.path || "" } : undefined
  });
}

function normalizeNetwork(value: string) {
  const network = value.toLowerCase();
  if (["tcp", "ws", "grpc", "h2", "http"].includes(network)) return network === "http" ? "h2" : network;
  return "tcp";
}

function normalizeSecurity(value: string) {
  const security = value.toLowerCase();
  if (security === "tls" || security === "reality") return security;
  return "none";
}

function parseShadowsocks(content: string) {
  const raw = content.replace(/^ss:\/\//i, "").split("#")[0] ?? "";
  if (!raw) return null;

  if (raw.includes("@")) {
    const [userinfoRaw, endpointRaw] = raw.split("@");
    const userinfo = userinfoRaw.includes(":") ? decodeURIComponent(userinfoRaw) : base64Decode(userinfoRaw);
    const endpoint = new URL(`ss://x@${endpointRaw}`);
    const [method, password] = splitFirst(userinfo, ":");
    const port = Number(endpoint.port);
    if (!method || !password || !endpoint.hostname || !port) return null;
    return { method, password, address: stripBrackets(endpoint.hostname), port };
  }

  const decoded = base64Decode(raw);
  const [userinfo, endpointText] = splitFirst(decoded, "@");
  const [method, password] = splitFirst(userinfo, ":");
  const endpoint = parseHostPort(endpointText);
  if (!method || !password || !endpoint) return null;
  return { method, password, address: endpoint.host, port: endpoint.port };
}

async function requestThroughLocalProxy(proxyPort: number, targetUrl: string, timeoutMs: number): Promise<ProbeResult> {
  const target = new URL(targetUrl);
  if (target.protocol === "https:") return requestHttpsThroughProxy(proxyPort, target, timeoutMs);
  if (target.protocol === "http:") return requestHttpThroughProxy(proxyPort, target, timeoutMs);
  return { ok: false, latencyMs: null, reason: "invalid_test_url" };
}

function requestHttpThroughProxy(proxyPort: number, target: URL, timeoutMs: number): Promise<ProbeResult> {
  const startedAt = Date.now();
  return new Promise((resolve) => {
    const req = http.request(
      {
        host: "127.0.0.1",
        port: proxyPort,
        method: "GET",
        path: target.href,
        headers: { Host: target.host, "User-Agent": "public-node-admin/1.0" },
        timeout: timeoutMs
      },
      (res) => {
        res.resume();
        res.on("end", () => {
          const ok = Boolean(res.statusCode && res.statusCode >= 200 && res.statusCode < 500);
          resolve({ ok, latencyMs: ok ? Date.now() - startedAt : null, reason: ok ? null : "proxy_failed" });
        });
      }
    );
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, latencyMs: null, reason: "proxy_timeout" });
    });
    req.on("error", () => resolve({ ok: false, latencyMs: null, reason: "proxy_failed" }));
    req.end();
  });
}

function requestHttpsThroughProxy(proxyPort: number, target: URL, timeoutMs: number): Promise<ProbeResult> {
  const startedAt = Date.now();
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result: ProbeResult) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    const socket = net.connect({ host: "127.0.0.1", port: proxyPort });
    const timer = setTimeout(() => {
      socket.destroy();
      finish({ ok: false, latencyMs: null, reason: "proxy_timeout" });
    }, timeoutMs);

    socket.once("connect", () => {
      socket.write(`CONNECT ${target.hostname}:443 HTTP/1.1\r\nHost: ${target.hostname}:443\r\n\r\n`);
    });
    socket.once("error", () => {
      clearTimeout(timer);
      finish({ ok: false, latencyMs: null, reason: "proxy_failed" });
    });
    socket.once("data", (chunk) => {
      const header = chunk.toString("utf8");
      if (!header.includes(" 200 ")) {
        clearTimeout(timer);
        socket.destroy();
        finish({ ok: false, latencyMs: null, reason: "proxy_failed" });
        return;
      }

      const secure = tls.connect({ socket, servername: target.hostname, rejectUnauthorized: false }, () => {
        const pathname = `${target.pathname || "/"}${target.search || ""}`;
        secure.write(`GET ${pathname} HTTP/1.1\r\nHost: ${target.hostname}\r\nConnection: close\r\nUser-Agent: public-node-admin/1.0\r\n\r\n`);
      });

      secure.once("data", (body) => {
        clearTimeout(timer);
        const firstLine = body.toString("utf8").split("\r\n")[0] ?? "";
        const ok = /^HTTP\/\d(?:\.\d)?\s+[234]\d\d/.test(firstLine);
        secure.destroy();
        finish({ ok, latencyMs: ok ? Date.now() - startedAt : null, reason: ok ? null : "proxy_failed" });
      });
      secure.once("error", () => {
        clearTimeout(timer);
        finish({ ok: false, latencyMs: null, reason: "proxy_failed" });
      });
    });
  });
}

async function waitForLocalPort(port: number, child: ChildProcess, timeoutMs: number) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) return false;
    if (await canConnectLocal(port)) return true;
    await sleep(150);
  }
  return false;
}

function canConnectLocal(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect({ host: "127.0.0.1", port });
    socket.setTimeout(500);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(false));
  });
}

async function stopProcess(child: ChildProcess | null) {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([onceExit(child), sleep(1500)]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

function onceExit(child: ChildProcess) {
  return new Promise<void>((resolve) => {
    child.once("exit", () => resolve());
  });
}

function recordXrayResult(testRunId: number, nodeId: number, realStatus: string, latencyMs: number | null, failureReason: string | null) {
  const now = new Date().toISOString();
  const qualityTier = latencyMs === null ? null : qualityTierForLatency(latencyMs);
  db.transaction(() => {
    db.prepare(
      `INSERT INTO node_test_results (test_run_id, node_id, status, latency_ms, failure_reason, tested_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    ).run(testRunId, nodeId, realStatus, latencyMs, failureReason, now);

    db.prepare(
      `UPDATE nodes
       SET real_status = ?, real_latency_ms = ?, real_tested_at = ?, test_method = 'xray-core',
           quality_tier = COALESCE(?, quality_tier),
           eligible_for_package = CASE WHEN ? = 'real_passed' THEN 1 WHEN ? = 'real_failed' THEN 0 ELSE eligible_for_package END,
           success_count = success_count + CASE WHEN ? = 'real_passed' THEN 1 ELSE 0 END,
           failure_count = failure_count + CASE WHEN ? = 'real_failed' THEN 1 ELSE 0 END,
           failure_reason = COALESCE(?, failure_reason), updated_at = ?
       WHERE id = ?`
    ).run(realStatus, latencyMs, now, qualityTier, realStatus, realStatus, realStatus, realStatus, failureReason, now, nodeId);
  })();
}

function qualityTierForLatency(latencyMs: number) {
  if (latencyMs <= 100) return "high";
  if (latencyMs <= 200) return "premium";
  if (latencyMs <= 300) return "community";
  return "backup";
}

async function runWithConcurrency<T>(items: T[], concurrency: number, worker: (item: T) => Promise<void>) {
  const queue = [...items];
  const workers = Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift();
      if (!item) return;
      await worker(item);
    }
  });
  await Promise.all(workers);
}

function randomLocalPort() {
  const min = Math.min(config.XRAY_LOCAL_PORT_MIN, config.XRAY_LOCAL_PORT_MAX);
  const max = Math.max(config.XRAY_LOCAL_PORT_MIN, config.XRAY_LOCAL_PORT_MAX);
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function base64Decode(value: string) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  return Buffer.from(padded, "base64").toString("utf8");
}

function splitFirst(value: string, separator: string): [string, string] {
  const index = value.indexOf(separator);
  if (index < 0) return [value, ""];
  return [value.slice(0, index), value.slice(index + separator.length)];
}

function parseHostPort(value: string) {
  const lastColon = value.lastIndexOf(":");
  if (lastColon <= 0) return null;
  const host = stripBrackets(value.slice(0, lastColon));
  const port = Number(value.slice(lastColon + 1));
  if (!host || !port) return null;
  return { host, port };
}

function stripBrackets(host: string) {
  return host.replace(/^\[/, "").replace(/\]$/, "");
}

function stripUndefined<T>(value: T): T {
  if (Array.isArray(value)) return value.map(stripUndefined) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, entry]) => entry !== undefined && entry !== "")
        .map(([key, entry]) => [key, stripUndefined(entry)])
    ) as T;
  }
  return value;
}

function normalizeFailureReason(value: string) {
  if (value === "unsupported_protocol") return value;
  if (value === "invalid_config") return value;
  return "invalid_config";
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
