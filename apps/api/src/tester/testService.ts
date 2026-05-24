import { config } from "../config.js";
import { db } from "../db.js";
import { testTcpConnection } from "./connectivity.js";
import { parseNodeEndpoint } from "./nodeEndpoint.js";

type NodeRow = {
  id: number;
  content: string;
  protocol: string;
};

type TestSummary = {
  runId: number;
  testedNodes: number;
  passedNodes: number;
  failedNodes: number;
  removedNodes: number;
  minLatencyMs: number | null;
  avgLatencyMs: number | null;
  maxLatencyMs: number | null;
};

let activeRun: Promise<TestSummary> | null = null;

export async function runNodeTests(options?: { limit?: number; includeFailed?: boolean }) {
  if (activeRun) return activeRun;
  activeRun = runNodeTestsInternal(options).finally(() => {
    activeRun = null;
  });
  return activeRun;
}

async function runNodeTestsInternal(options?: { limit?: number; includeFailed?: boolean }): Promise<TestSummary> {
  const limit = Math.max(1, Math.min(options?.limit ?? config.TEST_BATCH_SIZE, 1000));
  const statuses = options?.includeFailed ? ["pending_test", "test_failed"] : ["pending_test"];
  const placeholders = statuses.map(() => "?").join(",");
  const nodes = db
    .prepare(
      `SELECT id, content, protocol
       FROM nodes
       WHERE status IN (${placeholders})
       ORDER BY collected_at ASC
       LIMIT ?`
    )
    .all(...statuses, limit) as NodeRow[];

  const startedAt = new Date().toISOString();
  const runResult = db.prepare("INSERT INTO test_runs (status, started_at) VALUES ('running', ?)").run(startedAt);
  const runId = Number(runResult.lastInsertRowid);
  const latencies: number[] = [];
  let passedNodes = 0;
  let failedNodes = 0;

  await runWithConcurrency(nodes, config.TEST_MAX_CONCURRENCY, async (node) => {
    const endpoint = parseNodeEndpoint(node.content, node.protocol);
    if (!endpoint) {
      failedNodes += 1;
      recordNodeResult(runId, node.id, "test_failed", null, "parse_failed");
      return;
    }

    const result = await testTcpConnection(endpoint.host, endpoint.port);
    if (result.ok) {
      passedNodes += 1;
      latencies.push(result.latencyMs);
      recordNodeResult(runId, node.id, "test_passed", result.latencyMs, null);
    } else {
      failedNodes += 1;
      recordNodeResult(runId, node.id, "test_failed", null, result.reason);
    }
  });

  const summary: TestSummary = {
    runId,
    testedNodes: nodes.length,
    passedNodes,
    failedNodes,
    removedNodes: failedNodes,
    minLatencyMs: latencies.length ? Math.min(...latencies) : null,
    avgLatencyMs: latencies.length ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length) : null,
    maxLatencyMs: latencies.length ? Math.max(...latencies) : null
  };

  db.prepare(
    `UPDATE test_runs
     SET status = 'completed', finished_at = ?, tested_nodes = ?, passed_nodes = ?, failed_nodes = ?,
         removed_nodes = ?, min_latency_ms = ?, avg_latency_ms = ?, max_latency_ms = ?, summary_json = ?
     WHERE id = ?`
  ).run(
    new Date().toISOString(),
    summary.testedNodes,
    summary.passedNodes,
    summary.failedNodes,
    summary.removedNodes,
    summary.minLatencyMs,
    summary.avgLatencyMs,
    summary.maxLatencyMs,
    JSON.stringify(summary),
    runId
  );

  return summary;
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

function recordNodeResult(testRunId: number, nodeId: number, status: "test_passed" | "test_failed", latencyMs: number | null, failureReason: string | null) {
  const now = new Date().toISOString();
  const transaction = db.transaction(() => {
    db.prepare(
      `INSERT INTO node_test_results (test_run_id, node_id, status, latency_ms, failure_reason, tested_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    ).run(testRunId, nodeId, status, latencyMs, failureReason, now);

    db.prepare(
      `UPDATE nodes
       SET status = ?, latency_ms = ?, failure_reason = ?, last_tested_at = ?, updated_at = ?
           , test_method = 'tcp'
           , success_count = success_count + CASE WHEN ? = 'test_passed' THEN 1 ELSE 0 END
           , failure_count = failure_count + CASE WHEN ? = 'test_failed' THEN 1 ELSE 0 END
           , quality_tier = CASE
               WHEN ? IS NULL THEN quality_tier
               WHEN ? <= 100 THEN 'high'
               WHEN ? <= 200 THEN 'premium'
               WHEN ? <= 300 THEN 'community'
               ELSE 'backup'
             END
       WHERE id = ?`
    ).run(status, latencyMs, failureReason, now, now, status, status, latencyMs, latencyMs, latencyMs, latencyMs, nodeId);
  });
  transaction();
}
