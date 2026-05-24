import { execFile } from "node:child_process";
import fs from "node:fs";
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
      `SELECT id, protocol
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

  await runWithConcurrency(nodes, config.XRAY_REAL_TEST_CONCURRENCY, async (node) => {
    if (!configured) {
      skippedNodes += 1;
      recordXrayResult(runId, node.id, "xray_not_configured", null, "xray_not_configured");
      return;
    }
    if (!supportedProtocols.has(node.protocol)) {
      skippedNodes += 1;
      recordXrayResult(runId, node.id, "xray_unsupported_protocol", null, "unsupported_protocol");
      return;
    }

    const result = await probeXrayBinary();
    if (!result.ok) {
      failedNodes += 1;
      recordXrayResult(runId, node.id, "real_failed", null, result.reason);
      return;
    }

    skippedNodes += 1;
    recordXrayResult(runId, node.id, "xray_converter_pending", null, "xray_converter_pending");
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
  const startedAt = Date.now();
  try {
    await execFileAsync(config.XRAY_CORE_PATH, ["version"], {
      timeout: config.XRAY_REAL_TEST_TIMEOUT_MS,
      windowsHide: true
    });
    return { ok: true as const, latencyMs: Date.now() - startedAt };
  } catch {
    return { ok: false as const, reason: "xray_probe_failed" };
  }
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
           success_count = success_count + CASE WHEN ? = 'real_passed' THEN 1 ELSE 0 END,
           failure_count = failure_count + CASE WHEN ? = 'real_failed' THEN 1 ELSE 0 END,
           failure_reason = COALESCE(?, failure_reason), updated_at = ?
       WHERE id = ?`
    ).run(realStatus, latencyMs, now, qualityTier, realStatus, realStatus, failureReason, now, nodeId);
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
