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
  mode: XrayRunMode;
  limit: number;
  queueBefore: XrayQueueStats;
  queueAfter: XrayQueueStats;
};

type NodeRow = {
  id: number;
  protocol: string;
  content: string;
};

export type XrayRunMode = "untested" | "current" | "all" | "failed" | "range";

export type XrayRunOptions = {
  limit?: number;
  mode?: XrayRunMode;
  protocol?: string;
  minLatencyMs?: number;
  maxLatencyMs?: number;
  includePassed?: boolean;
  includeRecentFailures?: boolean;
};

export type XrayQueueStats = {
  candidateTotal: number;
  xrayChecked: number;
  xrayUnchecked: number;
  realPassed: number;
  realFailed: number;
  skipped: number;
  avgRealLatencyMs: number | null;
  tierHigh: number;
  tierPremium: number;
  tierCommunity: number;
  tierBackup: number;
  lastTestedAt: string | null;
};

export type XrayQueueRuntime = {
  status: "idle" | "running" | "paused" | "completed" | "stopped" | "failed";
  currentBatch: number;
  currentBatchSize: number;
  processedThisRun: number;
  message: string;
  startedAt: string | null;
  updatedAt: string | null;
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
const queueRuntime: XrayQueueRuntime & { pauseRequested: boolean; stopRequested: boolean } = {
  status: "idle",
  currentBatch: 0,
  currentBatchSize: 0,
  processedThisRun: 0,
  message: "未开始",
  startedAt: null,
  updatedAt: null,
  pauseRequested: false,
  stopRequested: false
};

export async function runXrayRealTests(options?: XrayRunOptions) {
  if (activeRun) return activeRun;
  activeRun = runXrayRealTestsInternal(options).finally(() => {
    activeRun = null;
  });
  return activeRun;
}

export function getXrayQueueStats(): XrayQueueStats {
  const row = db
    .prepare(
      `SELECT
         COUNT(*) AS candidateTotal,
         SUM(CASE WHEN real_tested_at IS NOT NULL AND real_status != 'xray_not_configured' THEN 1 ELSE 0 END) AS xrayChecked,
         SUM(CASE WHEN real_tested_at IS NULL OR real_status = 'xray_not_configured' THEN 1 ELSE 0 END) AS xrayUnchecked,
         SUM(CASE WHEN real_status = 'real_passed' THEN 1 ELSE 0 END) AS realPassed,
         SUM(CASE WHEN real_status = 'real_failed' THEN 1 ELSE 0 END) AS realFailed,
         SUM(CASE WHEN real_status LIKE 'xray_%' THEN 1 ELSE 0 END) AS skipped,
         AVG(CASE WHEN real_status = 'real_passed' THEN real_latency_ms ELSE NULL END) AS avgRealLatencyMs,
         SUM(CASE WHEN real_status = 'real_passed' AND real_latency_ms <= 100 THEN 1 ELSE 0 END) AS tierHigh,
         SUM(CASE WHEN real_status = 'real_passed' AND real_latency_ms > 100 AND real_latency_ms <= 200 THEN 1 ELSE 0 END) AS tierPremium,
         SUM(CASE WHEN real_status = 'real_passed' AND real_latency_ms > 200 AND real_latency_ms <= 300 THEN 1 ELSE 0 END) AS tierCommunity,
         SUM(CASE WHEN real_status = 'real_passed' AND real_latency_ms > 300 THEN 1 ELSE 0 END) AS tierBackup,
         MAX(real_tested_at) AS lastTestedAt
       FROM nodes
       WHERE status = 'test_passed'`
    )
    .get() as {
    candidateTotal: number | null;
    xrayChecked: number | null;
    xrayUnchecked: number | null;
    realPassed: number | null;
    realFailed: number | null;
    skipped: number | null;
    avgRealLatencyMs: number | null;
    tierHigh: number | null;
    tierPremium: number | null;
    tierCommunity: number | null;
    tierBackup: number | null;
    lastTestedAt: string | null;
  };

  return {
    candidateTotal: Number(row.candidateTotal ?? 0),
    xrayChecked: Number(row.xrayChecked ?? 0),
    xrayUnchecked: Number(row.xrayUnchecked ?? 0),
    realPassed: Number(row.realPassed ?? 0),
    realFailed: Number(row.realFailed ?? 0),
    skipped: Number(row.skipped ?? 0),
    avgRealLatencyMs: row.avgRealLatencyMs === null ? null : Math.round(Number(row.avgRealLatencyMs)),
    tierHigh: Number(row.tierHigh ?? 0),
    tierPremium: Number(row.tierPremium ?? 0),
    tierCommunity: Number(row.tierCommunity ?? 0),
    tierBackup: Number(row.tierBackup ?? 0),
    lastTestedAt: row.lastTestedAt ?? null
  };
}

export function getXrayQueueRuntime() {
  const { pauseRequested, stopRequested, ...runtime } = queueRuntime;
  return runtime;
}

export function pauseXrayQueue() {
  if (queueRuntime.status === "running") {
    queueRuntime.pauseRequested = true;
    queueRuntime.message = "已请求暂停，当前批次完成后暂停";
    queueRuntime.updatedAt = new Date().toISOString();
  }
  return getXrayQueueRuntime();
}

export function stopXrayQueue() {
  if (queueRuntime.status === "running" || queueRuntime.status === "paused") {
    queueRuntime.stopRequested = true;
    queueRuntime.pauseRequested = false;
    queueRuntime.status = queueRuntime.status === "paused" ? "stopped" : queueRuntime.status;
    queueRuntime.message = "已请求停止，当前批次完成后停止";
    queueRuntime.updatedAt = new Date().toISOString();
  }
  return getXrayQueueRuntime();
}

async function runXrayRealTestsInternal(options?: XrayRunOptions): Promise<XraySummary> {
  const mode = normalizeMode(options?.mode);
  const batchSize = Math.min(normalizeLimit(options?.limit), 200);
  const startedAt = new Date().toISOString();
  const queueBefore = getXrayQueueStats();
  queueRuntime.status = "running";
  queueRuntime.currentBatch = 0;
  queueRuntime.currentBatchSize = 0;
  queueRuntime.processedThisRun = 0;
  queueRuntime.message = "Xray-core 正在进行全量真实检测";
  queueRuntime.startedAt = startedAt;
  queueRuntime.updatedAt = startedAt;
  queueRuntime.pauseRequested = false;
  queueRuntime.stopRequested = false;
  const runResult = db
    .prepare("INSERT INTO test_runs (status, started_at, test_method) VALUES ('running', ?, 'xray-core')")
    .run(startedAt);
  const runId = Number(runResult.lastInsertRowid);

  const configured = await isXrayConfigured();
  let realPassedNodes = 0;
  let failedNodes = 0;
  let skippedNodes = 0;
  const latencies: number[] = [];

  const binaryProbe = configured ? await probeXrayBinary() : { ok: false, reason: "xray_not_configured" };

  while (!queueRuntime.stopRequested) {
    const nodes = selectXrayQueueNodes({ ...options, mode }, batchSize);
    if (!nodes.length) {
      queueRuntime.status = "completed";
      queueRuntime.message = "Xray-core 全量真实检测完成";
      break;
    }

    queueRuntime.currentBatch += 1;
    queueRuntime.currentBatchSize = nodes.length;
    queueRuntime.updatedAt = new Date().toISOString();

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

    queueRuntime.processedThisRun += nodes.length;
    queueRuntime.updatedAt = new Date().toISOString();

    if (queueRuntime.pauseRequested) {
      queueRuntime.status = "paused";
      queueRuntime.message = "Xray-core 检测已暂停，已完成结果已保存";
      break;
    }
    if (!configured || !binaryProbe.ok) {
      queueRuntime.status = "completed";
      queueRuntime.message = configured ? "Xray-core 启动检查失败，本轮已停止" : "Xray-core 未配置，本轮已停止";
      break;
    }
    if (mode === "current" || mode === "failed") {
      queueRuntime.status = "completed";
      queueRuntime.message = "Xray-core 当前批次检测完成";
      break;
    }
  }

  if (queueRuntime.stopRequested) {
    queueRuntime.status = "stopped";
    queueRuntime.message = "Xray-core 检测已停止，已完成结果已保存";
  }

  const summary: XraySummary = {
    runId,
    checkedNodes: queueRuntime.processedThisRun,
    realPassedNodes,
    failedNodes,
    skippedNodes,
    avgRealLatencyMs: latencies.length ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length) : null,
    configured,
    mode,
    limit: batchSize,
    queueBefore,
    queueAfter: getXrayQueueStats()
  };

  db.prepare(
    `UPDATE test_runs
     SET status = 'completed', finished_at = ?, tested_nodes = ?, passed_nodes = ?, failed_nodes = ?,
         removed_nodes = 0, avg_latency_ms = ?, summary_json = ?
     WHERE id = ?`
  ).run(new Date().toISOString(), summary.checkedNodes, realPassedNodes, failedNodes, summary.avgRealLatencyMs, JSON.stringify(summary), runId);

  return summary;
}

function selectXrayQueueNodes(options: XrayRunOptions, limit: number) {
  const mode = normalizeMode(options.mode);
  const where = ["status = 'test_passed'"];
  const params: unknown[] = [];
  const recentFailureCutoff = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();

  if (options.protocol && supportedProtocols.has(options.protocol)) {
    where.push("protocol = ?");
    params.push(options.protocol);
  }
  if (typeof options.minLatencyMs === "number" && Number.isFinite(options.minLatencyMs)) {
    where.push("COALESCE(real_latency_ms, latency_ms) >= ?");
    params.push(options.minLatencyMs);
  }
  if (typeof options.maxLatencyMs === "number" && Number.isFinite(options.maxLatencyMs)) {
    where.push("COALESCE(real_latency_ms, latency_ms) <= ?");
    params.push(options.maxLatencyMs);
  }

  if (mode === "failed") {
    where.push("real_status = 'real_failed'");
    if (!options.includeRecentFailures) {
      where.push("(real_tested_at IS NULL OR real_tested_at <= ?)");
      params.push(recentFailureCutoff);
    }
  } else if (mode === "current") {
    if (!options.includePassed) where.push("(real_status IS NULL OR real_status != 'real_passed')");
  } else {
    if (mode === "untested" || mode === "all" || mode === "range") {
      where.push("(real_tested_at IS NULL OR real_status = 'xray_not_configured')");
    }
    if (!options.includePassed) where.push("(real_status IS NULL OR real_status != 'real_passed')");
    if (!options.includeRecentFailures) {
      where.push("(real_status IS NULL OR real_status != 'real_failed' OR real_tested_at <= ?)");
      params.push(recentFailureCutoff);
    }
  }

  return db
    .prepare(
      `SELECT id, protocol, content
       FROM nodes
       WHERE ${where.join(" AND ")}
       ORDER BY
         CASE
           WHEN real_tested_at IS NULL OR real_status = 'xray_not_configured' THEN 0
           WHEN real_status = 'real_failed' THEN 1
           ELSE 2
         END,
         CASE WHEN real_latency_ms IS NULL THEN 1 ELSE 0 END,
         COALESCE(real_latency_ms, latency_ms, 999999) ASC,
         COALESCE(real_tested_at, last_tested_at, collected_at) ASC
       LIMIT ?`
    )
    .all(...params, limit) as NodeRow[];
}

function normalizeLimit(value?: number) {
  if (!Number.isFinite(value)) return 50;
  return Math.max(1, Math.min(Number(value), 5000));
}

function normalizeMode(value?: string): XrayRunMode {
  if (value === "current" || value === "all" || value === "failed" || value === "range") return value;
  return "untested";
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
