import type { FastifyInstance } from "fastify";
import { requireAdmin } from "./auth.js";
import { db } from "./db.js";

export function registerApiRoutes(app: FastifyInstance) {
  app.get("/health", async () => ({ ok: true, version: "0.1.0" }));

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
      version: "0.1.0",
      systemStatus: "running",
      candidateNodes: countStatus(nodeCounts, "test_passed"),
      pendingNodes: countStatus(nodeCounts, "pending_test"),
      failedNodes: countStatus(nodeCounts, "test_failed") + countStatus(nodeCounts, "removed"),
      publishedBatches: publishedBatches.count,
      recentCollection: recentCollection ?? null,
      recentTest: recentTest ?? null,
      latencyDistribution: [
        { label: "100ms 以内", count: 0 },
        { label: "100-200ms", count: 0 },
        { label: "200-300ms", count: 0 },
        { label: "300-500ms", count: 0 },
        { label: "500-800ms", count: 0 },
        { label: "800ms 以上", count: 0 }
      ]
    };
  });

  app.get("/api/nodes", { preHandler: requireAdmin }, async () => {
    return {
      items: [],
      message: "v0.1.0 已完成数据库和后台骨架，节点采集与候选池将在 v0.2.0/v0.3.0 实现。"
    };
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
