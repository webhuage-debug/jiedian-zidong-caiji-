import type { FastifyInstance } from "fastify";
import { requireAdmin } from "./auth.js";
import { runCollection } from "./collector/collectionService.js";
import { db } from "./db.js";
import { runNodeTests } from "./tester/testService.js";

export function registerApiRoutes(app: FastifyInstance) {
  app.get("/health", async () => ({ ok: true, version: "0.3.0" }));

  app.get("/api/dashboard/summary", { preHandler: requireAdmin }, async () => {
    const nodeCounts = db
      .prepare("SELECT status, COUNT(*) AS count FROM nodes GROUP BY status")
      .all() as Array<{ status: string; count: number }>;
    const publishedBatches = db.prepare("SELECT COUNT(*) AS count FROM export_batches WHERE status = 'published'").get() as {
      count: number;
    };
    const recentCollection = db
      .prepare("SELECT * FROM collection_runs ORDER BY started_at DESC LIMIT 1")
      .get() as Record<string, unknown> | undefined;
    const recentTest = db.prepare("SELECT * FROM test_runs ORDER BY started_at DESC LIMIT 1").get() as Record<string, unknown> | undefined;

    return {
      version: "0.3.0",
      systemStatus: "running",
      candidateNodes: countStatus(nodeCounts, "test_passed"),
      pendingNodes: countStatus(nodeCounts, "pending_test"),
      failedNodes: countStatus(nodeCounts, "test_failed") + countStatus(nodeCounts, "removed"),
      collectedNodes: sumCounts(nodeCounts),
      publishedBatches: publishedBatches.count,
      recentCollection: recentCollection ?? null,
      recentTest: recentTest ?? null,
      latencyDistribution: latencyDistribution()
    };
  });

  app.get("/api/nodes", { preHandler: requireAdmin }, async (request) => {
    const query = request.query as {
      protocol?: string;
      status?: string;
      sourceType?: string;
      minLatency?: string;
      maxLatency?: string;
      exported?: string;
      limit?: string;
      offset?: string;
    };
    const limit = clampNumber(Number(query.limit ?? 50), 1, 200);
    const offset = clampNumber(Number(query.offset ?? 0), 0, 100000);
    const where: string[] = [];
    const params: unknown[] = [];

    if (query.protocol) {
      where.push("protocol = ?");
      params.push(query.protocol);
    }
    if (query.status) {
      where.push("status = ?");
      params.push(query.status);
    }
    if (query.sourceType) {
      where.push("source_type = ?");
      params.push(query.sourceType);
    }
    if (query.minLatency) {
      where.push("latency_ms >= ?");
      params.push(Number(query.minLatency));
    }
    if (query.maxLatency) {
      where.push("latency_ms <= ?");
      params.push(Number(query.maxLatency));
    }
    if (query.exported === "true") {
      where.push("exported_at IS NOT NULL");
    }
    if (query.exported === "false") {
      where.push("exported_at IS NULL");
    }

    const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
    const items = db
      .prepare(
        `SELECT id, protocol, source_url, source_type, collected_at, last_tested_at,
                latency_ms, status, failure_reason, exported_at, export_batch_id
         FROM nodes
         ${whereSql}
         ORDER BY CASE WHEN latency_ms IS NULL THEN 1 ELSE 0 END, latency_ms ASC, collected_at DESC
         LIMIT ? OFFSET ?`
      )
      .all(...params, limit, offset);
    const total = db.prepare(`SELECT COUNT(*) AS count FROM nodes ${whereSql}`).get(...params) as { count: number };

    return { items, total: total.count };
  });

  app.get("/api/sources", { preHandler: requireAdmin }, async () => {
    return {
      items: db
        .prepare(
          `SELECT id, url, source_type, status, success_count, failure_count,
                  last_checked_at, next_allowed_at, last_error, updated_at
           FROM node_sources
           ORDER BY updated_at DESC
           LIMIT 200`
        )
        .all()
    };
  });

  app.get("/api/collection-runs", { preHandler: requireAdmin }, async () => {
    return {
      items: db.prepare("SELECT * FROM collection_runs ORDER BY id DESC LIMIT 50").all()
    };
  });

  app.get("/api/test-runs", { preHandler: requireAdmin }, async () => {
    return {
      items: db.prepare("SELECT * FROM test_runs ORDER BY id DESC LIMIT 50").all()
    };
  });

  app.post("/api/test-runs", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const body = (request.body ?? {}) as { limit?: number; includeFailed?: boolean };
      const summary = await runNodeTests({
        limit: body.limit,
        includeFailed: body.includeFailed
      });
      return { ok: true, summary };
    } catch (error) {
      const message = error instanceof Error ? error.message : "test failed";
      return reply.code(500).send({ ok: false, message });
    }
  });

  app.post("/api/collection-runs", { preHandler: requireAdmin }, async (_request, reply) => {
    try {
      const summary = await runCollection();
      return { ok: true, summary };
    } catch (error) {
      const message = error instanceof Error ? error.message : "collection failed";
      return reply.code(429).send({ ok: false, message });
    }
  });

  app.get("/api/logs", { preHandler: requireAdmin }, async () => {
    return {
      items: db.prepare("SELECT level, message, created_at FROM app_logs ORDER BY id DESC LIMIT 50").all()
    };
  });
}

function countStatus(rows: Array<{ status: string; count: number }>, status: string) {
  return rows.find((row) => row.status === status)?.count ?? 0;
}

function sumCounts(rows: Array<{ count: number }>) {
  return rows.reduce((total, row) => total + row.count, 0);
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, Math.trunc(value)));
}

function latencyDistribution() {
  const rows = db
    .prepare(
      `SELECT
        SUM(CASE WHEN latency_ms < 100 THEN 1 ELSE 0 END) AS under100,
        SUM(CASE WHEN latency_ms >= 100 AND latency_ms < 200 THEN 1 ELSE 0 END) AS from100To200,
        SUM(CASE WHEN latency_ms >= 200 AND latency_ms < 300 THEN 1 ELSE 0 END) AS from200To300,
        SUM(CASE WHEN latency_ms >= 300 AND latency_ms < 500 THEN 1 ELSE 0 END) AS from300To500,
        SUM(CASE WHEN latency_ms >= 500 AND latency_ms < 800 THEN 1 ELSE 0 END) AS from500To800,
        SUM(CASE WHEN latency_ms >= 800 THEN 1 ELSE 0 END) AS over800
       FROM nodes
       WHERE status = 'test_passed'`
    )
    .get() as Record<string, number | null>;

  return [
    { label: "100ms 以内", count: rows.under100 ?? 0 },
    { label: "100-200ms", count: rows.from100To200 ?? 0 },
    { label: "200-300ms", count: rows.from200To300 ?? 0 },
    { label: "300-500ms", count: rows.from300To500 ?? 0 },
    { label: "500-800ms", count: rows.from500To800 ?? 0 },
    { label: "800ms 以上", count: rows.over800 ?? 0 }
  ];
}
