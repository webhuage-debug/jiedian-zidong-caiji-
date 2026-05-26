import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import fs from "node:fs";
import path from "node:path";
import { requireAdmin } from "./auth.js";
import { runCollection } from "./collector/collectionService.js";
import { config } from "./config.js";
import { db } from "./db.js";
import { closeExportBatch, createExportBatch, createExportSchema, deleteDraftBatch, listExportBatches, preflightExportBatch, publishExportBatch } from "./exporter/exportService.js";
import { maskUrl, redactSensitiveText } from "./security/redact.js";
import { isPublicVideoModeEnabled, setSetting } from "./settings.js";
import {
  createSubscriptionActivity,
  createSubscriptionSchema,
  currentClaimInfo,
  generateSubscriptionCache,
  listSubscriptionActivities,
  preflightSubscriptionActivity,
  rebuildSubscriptionPool,
  runSubscriptionHealthCheck
} from "./subscription/subscriptionService.js";
import { runNodeTests } from "./tester/testService.js";
import { getXrayQueueRuntime, getXrayQueueStats, pauseXrayQueue, runXrayRealTests, stopXrayQueue, type XrayRunMode } from "./tester/xrayService.js";

export function registerApiRoutes(app: FastifyInstance) {
  app.get("/health", async () => ({ ok: true, version: "1.1.1" }));

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
      version: "1.1.1",
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
    const videoMode = isPublicVideoModeEnabled();
    const items = db
      .prepare(
        `SELECT id, protocol, source_url, source_type, collected_at, last_tested_at,
                latency_ms, real_latency_ms, real_status, real_tested_at, test_method,
                success_count, failure_count, quality_tier, eligible_for_package,
                status, failure_reason, exported_at, export_batch_id
         FROM nodes
         ${whereSql}
         ORDER BY CASE WHEN latency_ms IS NULL THEN 1 ELSE 0 END, latency_ms ASC, collected_at DESC
         LIMIT ? OFFSET ?`
      )
      .all(...params, limit, offset) as Array<Record<string, unknown>>;
    const total = db.prepare(`SELECT COUNT(*) AS count FROM nodes ${whereSql}`).get(...params) as { count: number };

    return {
      items: items.map((item) => ({
        ...item,
        source_url: videoMode ? maskUrl(item.source_url) : item.source_url,
        failure_reason: videoMode ? redactSensitiveText(item.failure_reason) : item.failure_reason
      })),
      total: total.count
    };
  });

  app.get("/api/sources", { preHandler: requireAdmin }, async () => {
    const videoMode = isPublicVideoModeEnabled();
    const items = db
      .prepare(
        `SELECT id, url, source_type, status, success_count, failure_count,
                last_checked_at, next_allowed_at, last_error, updated_at
         FROM node_sources
         ORDER BY updated_at DESC
         LIMIT 200`
      )
      .all() as Array<Record<string, unknown>>;
    return {
      items: items.map((item) => ({
        ...item,
        url: videoMode ? maskUrl(item.url) : item.url,
        last_error: videoMode ? redactSensitiveText(item.last_error) : item.last_error
      }))
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

  app.post("/api/xray-test-runs", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const body = (request.body ?? {}) as {
        limit?: number;
        mode?: XrayRunMode;
        protocol?: string;
        minLatencyMs?: number;
        maxLatencyMs?: number;
        includePassed?: boolean;
        includeRecentFailures?: boolean;
      };
      const summary = await runXrayRealTests({
        limit: clampNumber(Number(body.limit ?? 50), 1, 5000),
        mode: body.mode,
        protocol: body.protocol,
        minLatencyMs: body.minLatencyMs === undefined ? undefined : Number(body.minLatencyMs),
        maxLatencyMs: body.maxLatencyMs === undefined ? undefined : Number(body.maxLatencyMs),
        includePassed: Boolean(body.includePassed),
        includeRecentFailures: Boolean(body.includeRecentFailures)
      });
      return { ok: true, summary };
    } catch (error) {
      const message = error instanceof Error ? error.message : "xray real test failed";
      return reply.code(500).send({ ok: false, message });
    }
  });

  app.get("/api/xray-test-runs/stats", { preHandler: requireAdmin }, async () => {
    return {
      ...getXrayQueueStats(),
      configured: Boolean(config.XRAY_REAL_TEST_ENABLED && config.XRAY_CORE_PATH && fs.existsSync(config.XRAY_CORE_PATH)),
      runtime: getXrayQueueRuntime()
    };
  });

  app.post("/api/xray-test-runs/pause", { preHandler: requireAdmin }, async () => {
    return { ok: true, runtime: pauseXrayQueue() };
  });

  app.post("/api/xray-test-runs/stop", { preHandler: requireAdmin }, async () => {
    return { ok: true, runtime: stopXrayQueue() };
  });

  app.get("/api/export-batches", { preHandler: requireAdmin }, async () => {
    return { items: listExportBatches() };
  });

  app.post("/api/export-batches", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const input = createExportSchema.parse(request.body);
      const batch = await createExportBatch(input);
      return { ok: true, batch };
    } catch (error) {
      const message = error instanceof Error ? error.message : "export failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.post("/api/export-batches/:id/publish", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      publishExportBatch(Number(id));
      return { ok: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : "publish failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.post("/api/export-batches/:id/close", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      closeExportBatch(Number(id));
      return { ok: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : "close failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.post("/api/export-batches/:id/preflight", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      const summary = preflightExportBatch(Number(id));
      return { ok: true, summary };
    } catch (error) {
      const message = error instanceof Error ? error.message : "preflight failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.delete("/api/export-batches/:id", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      deleteDraftBatch(Number(id));
      return { ok: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : "delete failed";
      return reply.code(400).send({ ok: false, message });
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
    const videoMode = isPublicVideoModeEnabled();
    const logs = db.prepare("SELECT level, message, created_at FROM app_logs ORDER BY id DESC LIMIT 50").all() as Array<Record<string, unknown>>;
    return {
      items: logs.map((log) => ({
        ...log,
        message: videoMode ? redactSensitiveText(log.message) : log.message
      }))
    };
  });

  app.get("/api/stats/batches", { preHandler: requireAdmin }, async () => {
    return {
      items: db
        .prepare(
          `SELECT export_batches.id, export_batches.batch_code, export_batches.name, export_batches.status,
                  export_batches.node_count, export_batches.public_slug,
                  batch_stats.view_count, batch_stats.passphrase_attempt_count,
                  batch_stats.passphrase_correct_count, batch_stats.passphrase_wrong_count,
                  batch_stats.unlock_count, batch_stats.download_count, batch_stats.feedback_count,
                  batch_stats.updated_at
           FROM export_batches
           LEFT JOIN batch_stats ON batch_stats.batch_id = export_batches.id
           ORDER BY export_batches.id DESC
           LIMIT 100`
        )
        .all()
    };
  });

  app.get("/api/stats/channels", { preHandler: requireAdmin }, async () => {
    return {
      items: db
        .prepare(
          `SELECT COALESCE(source_platform, 'direct') AS source_platform,
                  SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS view_count,
                  SUM(CASE WHEN event_type = 'passphrase_attempt' THEN 1 ELSE 0 END) AS passphrase_attempt_count,
                  SUM(CASE WHEN event_type = 'passphrase_wrong' THEN 1 ELSE 0 END) AS passphrase_wrong_count,
                  SUM(CASE WHEN event_type = 'passphrase_correct' THEN 1 ELSE 0 END) AS passphrase_correct_count,
                  SUM(CASE WHEN event_type = 'download' THEN 1 ELSE 0 END) AS download_count,
                  (SELECT COUNT(*) FROM feedback WHERE COALESCE(feedback.source_platform, 'direct') = COALESCE(public_events.source_platform, 'direct')) AS feedback_count,
                  (SELECT COUNT(*) FROM feedback WHERE COALESCE(feedback.source_platform, 'direct') = COALESCE(public_events.source_platform, 'direct') AND is_usable = 0) AS unusable_feedback_count,
                  MAX(created_at) AS last_seen_at
           FROM public_events
           GROUP BY COALESCE(source_platform, 'direct')
           ORDER BY view_count DESC
           LIMIT 50`
        )
        .all()
    };
  });

  app.get("/api/feedback", { preHandler: requireAdmin }, async () => {
    return {
      items: db
        .prepare(
          `SELECT feedback.id,
                  COALESCE(export_batches.batch_code, subscription_activities.name) AS batch_code,
                  feedback.subscription_activity_id, feedback.subscription_token,
                  feedback.region, feedback.carrier,
                  feedback.device, feedback.client_app, feedback.is_usable, feedback.issue_type,
                  feedback.source_platform, feedback.process_status, feedback.process_note,
                  feedback.note, feedback.created_at
           FROM feedback
           LEFT JOIN export_batches ON export_batches.id = feedback.batch_id
           LEFT JOIN subscription_activities ON subscription_activities.id = feedback.subscription_activity_id
           ORDER BY feedback.id DESC
           LIMIT 100`
        )
        .all()
    };
  });

  app.patch("/api/feedback/:id", { preHandler: requireAdmin }, async (request, reply) => {
    const { id } = request.params as { id: string };
    const body = (request.body ?? {}) as { processStatus?: string; processNote?: string };
    const allowedStatus = new Set(["pending", "viewed", "resolved", "invalid", "regenerate"]);
    const processStatus = String(body.processStatus ?? "").trim();
    const processNote = body.processNote ? String(body.processNote).trim().slice(0, 200) : null;

    if (!allowedStatus.has(processStatus)) {
      return reply.status(400).send({ message: "处理状态无效" });
    }

    const result = db
      .prepare("UPDATE feedback SET process_status = ?, process_note = ? WHERE id = ?")
      .run(processStatus, processNote, Number(id));
    if (!result.changes) return reply.status(404).send({ message: "反馈不存在" });

    return { ok: true };
  });

  app.get("/api/settings/video-mode", { preHandler: requireAdmin }, async () => {
    return { enabled: isPublicVideoModeEnabled() };
  });

  app.post("/api/settings/video-mode", { preHandler: requireAdmin }, async (request) => {
    const body = (request.body ?? {}) as { enabled?: boolean };
    setSetting("public_video_mode", body.enabled ? "true" : "false");
    return { enabled: Boolean(body.enabled) };
  });

  app.get("/api/subscriptions", { preHandler: requireAdmin }, async () => {
    return { items: listSubscriptionActivities() };
  });

  app.post("/api/subscriptions", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const input = createSubscriptionSchema.parse(request.body);
      const item = createSubscriptionActivity(input);
      return { ok: true, item };
    } catch (error) {
      const message = error instanceof Error ? error.message : "subscription create failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.post("/api/subscriptions/:id/rebuild", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      return { ok: true, summary: rebuildSubscriptionPool(Number(id)) };
    } catch (error) {
      const message = error instanceof Error ? error.message : "subscription rebuild failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.post("/api/subscriptions/:id/health-check", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      return { ok: true, summary: runSubscriptionHealthCheck(Number(id)) };
    } catch (error) {
      const message = error instanceof Error ? error.message : "subscription health check failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.post("/api/subscriptions/:id/cache", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      return { ok: true, summary: generateSubscriptionCache(Number(id)) };
    } catch (error) {
      const message = error instanceof Error ? error.message : "subscription cache failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.post("/api/subscriptions/:id/preflight", { preHandler: requireAdmin }, async (request, reply) => {
    try {
      const { id } = request.params as { id: string };
      return { ok: true, summary: preflightSubscriptionActivity(Number(id)) };
    } catch (error) {
      const message = error instanceof Error ? error.message : "subscription preflight failed";
      return reply.code(400).send({ ok: false, message });
    }
  });

  app.get("/api/public/current-claim", async () => {
    return { item: currentClaimInfo() };
  });

  app.get("/api/automation/packages", { preHandler: requireAutomationToken }, async () => {
    return { items: automationPackages() };
  });

  app.get("/api/automation/current-package", { preHandler: requireAutomationToken }, async () => {
    return { item: automationPackages()[0] ?? null };
  });

  app.get("/api/automation/packages/:id/download", { preHandler: requireAutomationToken }, async (request, reply) => {
    const { id } = request.params as { id: string };
    const batch = db
      .prepare(
        `SELECT id, batch_code, package_path, allow_hermes_file
         FROM export_batches
         WHERE id = ? AND status = 'published' AND allow_automation = 1 AND allow_hermes_file = 1`
      )
      .get(Number(id)) as { id: number; batch_code: string; package_path: string; allow_hermes_file: number } | undefined;
    if (!batch || !isExportPathAllowed(batch.package_path) || !fs.existsSync(batch.package_path)) {
      return reply.code(404).send({ message: "文件不可用" });
    }
    reply.header("Content-Type", "application/zip");
    reply.header("Content-Disposition", `attachment; filename="${encodeURIComponent(batch.batch_code)}.zip"`);
    return reply.send(fs.createReadStream(batch.package_path));
  });

  app.get("/api/automation/channel-links", { preHandler: requireAutomationToken }, async () => {
    const current = automationPackages()[0];
    if (!current) return { items: [] };
    const channels = ["youtube", "telegram", "facebook", "x", "tiktok"];
    return {
      items: channels.map((channel) => ({
        channel,
        claimUrl: current.allow_hermes_link ? `${config.PUBLIC_BASE_URL}/r/${current.public_slug}?from=${channel}` : null,
        qualityTier: current.quality_tier,
        expiresAt: current.expires_at
      }))
    };
  });

  app.get("/api/automation/daily-summary", { preHandler: requireAutomationToken }, async () => {
    const current = automationPackages()[0];
    if (!current) return { title: "今日免费节点暂未更新", summaryText: "当前没有允许自动化读取的已发布节点包。", recommendedClients: [] };
    const claimUrl = current.allow_hermes_link ? `${config.PUBLIC_BASE_URL}/r/${current.public_slug}` : null;
    return {
      title: "今日免费节点已更新",
      summaryText: `今日免费节点已更新\n\n节点包类型：${qualityTierName(current.quality_tier)}\n推荐客户端：v2rayN / Clash Verge / Shadowrocket\n领取地址：${claimUrl ?? "请到公开领取页查看"}`,
      claimUrl,
      fileDownloadUrl: current.allow_hermes_file ? `${config.PUBLIC_BASE_URL}/api/automation/packages/${current.id}/download` : null,
      packageQuality: current.quality_tier,
      latencyRange: qualityTierRange(current.quality_tier),
      nodeCount: current.node_count,
      expiresAt: current.expires_at,
      recommendedClients: ["v2rayN", "Clash Verge", "Shadowrocket", "sing-box"],
      notice: "免费节点存在时效性，部分节点失效属于正常情况，请以实际使用为准。"
    };
  });

  app.get("/api/automation/stats-summary", { preHandler: requireAutomationToken }, async () => {
    return {
      packages: automationPackages().length,
      channels: db
        .prepare(
          `SELECT COALESCE(source_platform, 'direct') AS source_platform,
                  COUNT(*) AS event_count,
                  SUM(CASE WHEN event_type = 'download' THEN 1 ELSE 0 END) AS download_count
           FROM public_events
           GROUP BY COALESCE(source_platform, 'direct')
           ORDER BY event_count DESC`
        )
        .all()
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

function requireAutomationToken(request: FastifyRequest, reply: FastifyReply, done: (error?: Error) => void) {
  if (!config.AUTOMATION_API_TOKEN) {
    reply.code(503).send({ message: "自动化接口未启用" });
    return;
  }
  const header = request.headers.authorization ?? request.headers["x-api-token"];
  const token = String(header ?? "").replace(/^Bearer\s+/i, "");
  if (token !== config.AUTOMATION_API_TOKEN) {
    reply.code(401).send({ message: "自动化 Token 无效" });
    return;
  }
  done();
}

function automationPackages() {
  return db
    .prepare(
      `SELECT id, name, status, node_count, public_slug, quality_tier, expires_at,
              allow_automation, allow_direct_download, allow_hermes_file, allow_hermes_link,
              max_downloads, ip_download_limit, created_at, updated_at
       FROM export_batches
       WHERE status = 'published'
         AND allow_automation = 1
         AND (expires_at IS NULL OR expires_at > ?)
         AND (quality_tier IS NULL OR quality_tier != 'high' OR (allow_hermes_file = 1 OR allow_hermes_link = 1))
       ORDER BY published_at DESC, id DESC
       LIMIT 20`
    )
    .all(new Date().toISOString()) as Array<Record<string, any>>;
}

function qualityTierName(value?: string | null) {
  const names: Record<string, string> = {
    high: "高质量节点包",
    premium: "普通优质节点包",
    community: "社群福利节点包",
    backup: "备用节点包"
  };
  return value ? names[value] ?? value : "普通福利包";
}

function qualityTierRange(value?: string | null) {
  const ranges: Record<string, string> = {
    high: "0-100ms",
    premium: "100-200ms",
    community: "200-300ms",
    backup: "300ms 以上"
  };
  return value ? ranges[value] ?? null : null;
}

function isExportPathAllowed(filePath: string) {
  const resolved = path.resolve(filePath);
  return resolved.startsWith(config.EXPORT_DIR + path.sep);
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
