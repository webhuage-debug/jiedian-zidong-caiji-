import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import bcrypt from "bcryptjs";
import { nanoid } from "nanoid";
import { z } from "zod";
import { config } from "../config.js";
import { db } from "../db.js";

export const createSubscriptionSchema = z.object({
  name: z.string().min(1).max(120),
  videoNote: z.string().max(500).optional().default(""),
  passphrase: z.string().min(4).max(128),
  startsAt: z.string().datetime().optional(),
  expiresAt: z.string().datetime().optional(),
  outputCount: z.coerce.number().int().positive().max(200).default(config.SUBSCRIPTION_DEFAULT_OUTPUT_COUNT),
  targetLatencyMs: z.coerce.number().int().positive().max(2000).default(200),
  warningLatencyMs: z.coerce.number().int().positive().max(3000).default(300),
  removeLatencyMs: z.coerce.number().int().positive().max(5000).default(500),
  healthCheckIntervalMinutes: z.coerce.number().int().positive().max(1440).default(5)
});

type CreateSubscriptionInput = z.infer<typeof createSubscriptionSchema>;

type ActivityRow = {
  id: number;
  name: string;
  video_note: string | null;
  status: string;
  claim_slug: string;
  subscription_token: string;
  passphrase_hash: string | null;
  starts_at: string;
  expires_at: string;
  output_count: number;
  target_latency_ms: number;
  warning_latency_ms: number;
  remove_latency_ms: number;
  health_check_interval_minutes: number;
  last_health_check_at: string | null;
  last_cache_generated_at: string | null;
  last_replacement_count: number;
  risk_status: string;
  risk_message: string | null;
  created_at: string;
  updated_at: string;
};

type SubNode = {
  id: number;
  content: string;
  real_latency_ms: number | null;
  real_tested_at: string | null;
  success_count: number;
  failure_count: number;
  region: string;
};

export function createSubscriptionActivity(input: CreateSubscriptionInput) {
  const options = createSubscriptionSchema.parse(input);
  const now = new Date();
  const startsAt = options.startsAt ? new Date(options.startsAt) : now;
  const expiresAt = options.expiresAt ? new Date(options.expiresAt) : new Date(startsAt.getTime() + config.SUBSCRIPTION_DEFAULT_DAYS * 24 * 60 * 60 * 1000);
  const claimSlug = `yt-${startsAt.toISOString().slice(0, 10).replace(/-/g, "")}-${nanoid(8)}`;
  const token = `${claimSlug}-${nanoid(10)}`;
  const passphraseHash = bcrypt.hashSync(options.passphrase, 12);
  const isoNow = now.toISOString();

  const id = db.transaction(() => {
    const result = db
      .prepare(
        `INSERT INTO subscription_activities (
          name, video_note, status, claim_slug, subscription_token, passphrase_hash,
          starts_at, expires_at, output_count, target_latency_ms, warning_latency_ms, remove_latency_ms,
          health_check_interval_minutes, created_at, updated_at
        )
        VALUES (?, ?, 'published', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        options.name,
        options.videoNote,
        claimSlug,
        token,
        passphraseHash,
        startsAt.toISOString(),
        expiresAt.toISOString(),
        options.outputCount,
        options.targetLatencyMs,
        options.warningLatencyMs,
        options.removeLatencyMs,
        options.healthCheckIntervalMinutes,
        isoNow,
        isoNow
      );
    const activityId = Number(result.lastInsertRowid);
    db.prepare("INSERT INTO subscription_stats (activity_id, updated_at) VALUES (?, ?)").run(activityId, isoNow);
    rebuildSubscriptionPool(activityId);
    generateSubscriptionCache(activityId);
    return activityId;
  })();

  logSubscription("success", `订阅活动创建：活动 ${id}`);
  return getSubscriptionActivity(id);
}

export function listSubscriptionActivities() {
  return db
    .prepare(
      `SELECT subscription_activities.*,
              subscription_stats.view_count, subscription_stats.raw_access_count, subscription_stats.base64_access_count,
              subscription_stats.feedback_count, subscription_stats.active_ip_count
       FROM subscription_activities
       LEFT JOIN subscription_stats ON subscription_stats.activity_id = subscription_activities.id
       ORDER BY subscription_activities.id DESC
       LIMIT 100`
    )
    .all();
}

export function getSubscriptionActivity(id: number) {
  return db.prepare("SELECT * FROM subscription_activities WHERE id = ?").get(id) as ActivityRow | undefined;
}

export function getPublicSubscriptionBySlug(slug: string) {
  const row = db.prepare("SELECT * FROM subscription_activities WHERE claim_slug = ?").get(slug) as ActivityRow | undefined;
  return normalizeActivity(row);
}

export function getPublicSubscriptionByToken(token: string) {
  const row = db.prepare("SELECT * FROM subscription_activities WHERE subscription_token = ?").get(token) as ActivityRow | undefined;
  return normalizeActivity(row);
}

export function verifySubscriptionPassphrase(activity: ActivityRow, passphrase: string) {
  return activity.passphrase_hash ? bcrypt.compareSync(passphrase, activity.passphrase_hash) : false;
}

export function getSubscriptionPublicInfo(activity: ActivityRow, unlocked: boolean) {
  return {
    mode: "subscription",
    title: activity.name,
    description: activity.video_note || "输入本期视频口令后，可领取 raw / base64 通用订阅链接。",
    startsAt: activity.starts_at,
    expiresAt: activity.expires_at,
    remainingSeconds: Math.max(0, Math.floor((new Date(activity.expires_at).getTime() - Date.now()) / 1000)),
    status: activity.status,
    riskStatus: activity.risk_status,
    riskMessage: activity.risk_message,
    outputCount: countActivityNodes(activity.id),
    unlocked,
    rawUrl: unlocked ? `${config.PUBLIC_BASE_URL}/sub/${activity.subscription_token}/raw` : null,
    base64Url: unlocked ? `${config.PUBLIC_BASE_URL}/sub/${activity.subscription_token}/base64` : null
  };
}

export function readSubscriptionCache(activity: ActivityRow, format: "raw" | "base64") {
  if (isExpired(activity)) return "本期订阅已过期，请查看华哥最新 YouTube 视频获取新一期订阅。\n";
  const cachePath = cacheFile(activity.subscription_token, format);
  if (!fs.existsSync(cachePath)) generateSubscriptionCache(activity.id);
  return fs.existsSync(cachePath) ? fs.readFileSync(cachePath, "utf8") : "当前真实可用节点不足，系统正在继续检测候选节点。\n";
}

export function generateSubscriptionCache(activityId: number) {
  const activity = getSubscriptionActivity(activityId);
  if (!activity) throw new Error("subscription activity not found");
  const nodes = currentActivityNodes(activityId);
  const raw = nodes.map((node) => node.content).join("\n") + (nodes.length ? "\n" : "");
  fs.mkdirSync(config.SUB_CACHE_DIR, { recursive: true });
  fs.writeFileSync(cacheFile(activity.subscription_token, "raw"), raw || "当前真实可用节点不足，系统正在继续检测候选节点。\n", "utf8");
  fs.writeFileSync(cacheFile(activity.subscription_token, "base64"), Buffer.from(raw, "utf8").toString("base64"), "utf8");
  const riskMessage = nodes.length < activity.output_count ? `真实可用节点不足，当前订阅只输出 ${nodes.length} 条，系统正在继续检测候选节点。` : null;
  db.prepare(
    `UPDATE subscription_activities
     SET last_cache_generated_at = ?, risk_status = ?, risk_message = ?, updated_at = ?
     WHERE id = ?`
  ).run(new Date().toISOString(), riskMessage ? "warning" : "normal", riskMessage, new Date().toISOString(), activityId);
  logSubscription("info", `订阅缓存生成：活动 ${activityId}，输出 ${nodes.length} 条`);
  return { nodeCount: nodes.length, riskMessage };
}

export function rebuildSubscriptionPool(activityId: number) {
  const activity = getSubscriptionActivity(activityId);
  if (!activity) throw new Error("subscription activity not found");
  const nodes = selectOutputNodes(activity.output_count);
  const now = new Date().toISOString();
  db.prepare("DELETE FROM subscription_activity_nodes WHERE activity_id = ?").run(activityId);
  const insert = db.prepare(
    `INSERT OR IGNORE INTO subscription_activity_nodes (activity_id, node_id, region_group, added_at)
     VALUES (?, ?, ?, ?)`
  );
  for (const node of nodes) insert.run(activityId, node.id, node.region, now);
  generateSubscriptionCache(activityId);
  return { selected: nodes.length, target: activity.output_count };
}

export function runSubscriptionHealthCheck(activityId: number) {
  const activity = getSubscriptionActivity(activityId);
  if (!activity) throw new Error("subscription activity not found");
  const now = new Date().toISOString();
  const current = currentActivityNodes(activityId);
  const badIds = current
    .filter((node) => shouldReplaceNode(node, activity))
    .map((node) => node.id);
  if (badIds.length) {
    db.prepare(`DELETE FROM subscription_activity_nodes WHERE activity_id = ? AND node_id IN (${badIds.map(() => "?").join(",")})`).run(activityId, ...badIds);
  }
  const need = Math.max(0, activity.output_count - countActivityNodes(activityId));
  if (need > 0) {
    const excluded = currentActivityNodes(activityId).map((node) => node.id);
    const replacements = selectOutputNodes(need, excluded);
    const insert = db.prepare(
      `INSERT OR IGNORE INTO subscription_activity_nodes (activity_id, node_id, region_group, added_at, last_checked_at)
       VALUES (?, ?, ?, ?, ?)`
    );
    for (const node of replacements) insert.run(activityId, node.id, node.region, now, now);
  }
  db.prepare("UPDATE subscription_activities SET last_health_check_at = ?, last_replacement_count = ?, updated_at = ? WHERE id = ?").run(now, badIds.length, now, activityId);
  const cache = generateSubscriptionCache(activityId);
  logSubscription("success", `订阅健康检查完成：活动 ${activity.id}，替换 ${badIds.length} 条，当前输出 ${countActivityNodes(activityId)} 条`);
  return { removed: badIds.length, currentCount: countActivityNodes(activityId), riskMessage: cache.riskMessage };
}

export function recordSubscriptionEvent(activityId: number, eventType: string, sourcePlatform: string | null, ipHash: string, userAgent: string) {
  const now = new Date().toISOString();
  db.prepare(
    `INSERT INTO subscription_access_events (activity_id, event_type, source_platform, ip_hash, user_agent, created_at)
     VALUES (?, ?, ?, ?, ?, ?)`
  ).run(activityId, eventType, sourcePlatform, ipHash, userAgent, now);
  updateAccessRisk(activityId);
}

export function incrementSubscriptionStat(activityId: number, field: "view_count" | "passphrase_attempt_count" | "passphrase_correct_count" | "passphrase_wrong_count" | "unlock_count" | "raw_access_count" | "base64_access_count" | "feedback_count") {
  db.prepare(`UPDATE subscription_stats SET ${field} = ${field} + 1, updated_at = ? WHERE activity_id = ?`).run(new Date().toISOString(), activityId);
}

export function currentClaimInfo() {
  const activity = db
    .prepare("SELECT * FROM subscription_activities WHERE status = 'published' AND expires_at > ? ORDER BY starts_at DESC, id DESC LIMIT 1")
    .get(new Date().toISOString()) as ActivityRow | undefined;
  if (!activity) return null;
  return {
    title: activity.name,
    claimUrl: `${config.PUBLIC_BASE_URL}/r/${activity.claim_slug}`,
    expiresAt: activity.expires_at,
    message: "请打开领取页，并在华哥最新 YouTube 视频中获取本期口令。"
  };
}

export function runDueSubscriptionHealthChecks() {
  const now = new Date();
  const candidates = db
    .prepare("SELECT * FROM subscription_activities WHERE status = 'published' ORDER BY id ASC")
    .all() as ActivityRow[];
  const due = candidates.filter((activity) => {
    if (isExpired(activity)) {
      normalizeActivity(activity);
      logSubscription("info", `订阅活动已过期：活动 ${activity.id}`);
      return false;
    }
    if (!activity.last_health_check_at) return true;
    const last = new Date(activity.last_health_check_at).getTime();
    const intervalMs = Math.max(1, activity.health_check_interval_minutes) * 60 * 1000;
    return now.getTime() - last >= intervalMs;
  });

  let checked = 0;
  let replaced = 0;
  for (const activity of due) {
    try {
      const summary = runSubscriptionHealthCheck(activity.id);
      checked += 1;
      replaced += summary.removed;
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown";
      logSubscription("error", `订阅健康检查失败：活动 ${activity.id}，${redactLogMessage(message)}`);
    }
  }
  return { checked, replaced };
}

export function startSubscriptionMaintenance(logger?: { info: (value: unknown) => void; error: (value: unknown) => void }) {
  const intervalMs = Math.max(60, config.SUBSCRIPTION_CACHE_MAX_AGE_SECONDS) * 1000;
  const tick = () => {
    try {
      const summary = runDueSubscriptionHealthChecks();
      if (summary.checked > 0) logger?.info({ msg: "subscription maintenance completed", ...summary });
    } catch (error) {
      logger?.error(error);
      const message = error instanceof Error ? error.message : "unknown";
      logSubscription("error", `订阅自动维护失败：${redactLogMessage(message)}`);
    }
  };
  const timer = setInterval(tick, intervalMs);
  timer.unref?.();
  setTimeout(tick, 5000).unref?.();
  logSubscription("info", `订阅自动健康检查已启动，周期 ${Math.round(intervalMs / 1000)} 秒`);
  return () => clearInterval(timer);
}

function normalizeActivity(activity?: ActivityRow) {
  if (!activity) return null;
  if (activity.status !== "published") return null;
  if (isExpired(activity)) {
    db.prepare("UPDATE subscription_activities SET status = 'expired', updated_at = ? WHERE id = ?").run(new Date().toISOString(), activity.id);
    return { ...activity, status: "expired" };
  }
  return activity;
}

function isExpired(activity: ActivityRow) {
  return new Date(activity.expires_at).getTime() <= Date.now();
}

function shouldReplaceNode(node: SubNode, activity: ActivityRow) {
  if (node.real_latency_ms === null) return true;
  if (node.real_latency_ms > activity.remove_latency_ms) return true;
  if (!node.real_tested_at) return true;
  const maxAgeMs = 30 * 60 * 1000;
  return Date.now() - new Date(node.real_tested_at).getTime() > maxAgeMs;
}

function selectOutputNodes(limit: number, excludeIds: number[] = []) {
  const params: unknown[] = [];
  const excludeSql = excludeIds.length ? `AND nodes.id NOT IN (${excludeIds.map(() => "?").join(",")})` : "";
  params.push(...excludeIds, limit);
  return db
    .prepare(
      `SELECT id, content, real_latency_ms, real_tested_at, success_count, failure_count,
              CASE
                WHEN source_url LIKE '%hk%' OR source_url LIKE '%hong%' OR content LIKE '%hk%' THEN '香港'
                WHEN source_url LIKE '%jp%' OR source_url LIKE '%japan%' OR content LIKE '%jp%' THEN '日本'
                WHEN source_url LIKE '%sg%' OR source_url LIKE '%singapore%' OR content LIKE '%sg%' THEN '新加坡'
                WHEN source_url LIKE '%us%' OR source_url LIKE '%america%' OR content LIKE '%us%' THEN '美国'
                WHEN source_url LIKE '%tw%' OR source_url LIKE '%taiwan%' OR content LIKE '%tw%' THEN '台湾'
                WHEN source_url LIKE '%kr%' OR source_url LIKE '%korea%' OR content LIKE '%kr%' THEN '韩国'
                ELSE '其他'
              END AS region
       FROM nodes
       WHERE status IN ('test_passed', 'exported')
         AND real_status = 'real_passed'
         AND real_latency_ms IS NOT NULL
         AND eligible_for_package = 1
         ${excludeSql}
       ORDER BY real_latency_ms ASC, success_count DESC, real_tested_at DESC
       LIMIT ?`
    )
    .all(...params) as SubNode[];
}

function currentActivityNodes(activityId: number) {
  return db
    .prepare(
      `SELECT nodes.id, nodes.content, nodes.real_latency_ms, nodes.real_tested_at,
              nodes.success_count, nodes.failure_count,
              COALESCE(subscription_activity_nodes.region_group, '其他') AS region
       FROM subscription_activity_nodes
       JOIN nodes ON nodes.id = subscription_activity_nodes.node_id
       WHERE subscription_activity_nodes.activity_id = ?
         AND subscription_activity_nodes.replaced_at IS NULL
       ORDER BY nodes.real_latency_ms ASC`
    )
    .all(activityId) as SubNode[];
}

function countActivityNodes(activityId: number) {
  const row = db.prepare("SELECT COUNT(*) AS count FROM subscription_activity_nodes WHERE activity_id = ? AND replaced_at IS NULL").get(activityId) as { count: number };
  return row.count;
}

function cacheFile(token: string, format: "raw" | "base64") {
  const safeToken = token.replace(/[^a-zA-Z0-9_-]/g, "");
  return path.join(config.SUB_CACHE_DIR, `${safeToken}.${format === "raw" ? "raw.txt" : "base64.txt"}`);
}

export function hashSubscriptionIp(ip: string) {
  return crypto.createHmac("sha256", config.SESSION_SECRET).update(ip).digest("hex");
}

function updateAccessRisk(activityId: number) {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const row = db
    .prepare("SELECT COUNT(DISTINCT ip_hash) AS count FROM subscription_access_events WHERE activity_id = ? AND created_at >= ?")
    .get(activityId, since) as { count: number };
  const activeIpCount = row.count ?? 0;
  let riskStatus = "normal";
  let riskMessage: string | null = null;
  if (activeIpCount > 30) {
    riskStatus = "high";
    riskMessage = "订阅 token 访问来源异常偏多，建议暂停或替换本期订阅。";
  } else if (activeIpCount > 10) {
    riskStatus = "medium";
    riskMessage = "订阅 token 活跃 IP 偏多，建议关注传播范围。";
  } else if (activeIpCount > 5) {
    riskStatus = "low";
    riskMessage = "订阅 token 已超过 5 个活跃 IP，已标记轻微风险。";
  }
  db.prepare("UPDATE subscription_stats SET active_ip_count = ?, updated_at = ? WHERE activity_id = ?").run(activeIpCount, new Date().toISOString(), activityId);
  if (riskStatus !== "normal") {
    db.prepare("UPDATE subscription_activities SET risk_status = ?, risk_message = ?, updated_at = ? WHERE id = ?").run(riskStatus, riskMessage, new Date().toISOString(), activityId);
    logSubscription("warning", `订阅 token 风险标记：活动 ${activityId}，活跃 IP ${activeIpCount}`);
  }
}

function logSubscription(level: "info" | "warning" | "error" | "success", message: string) {
  db.prepare("INSERT INTO app_logs (level, message, created_at) VALUES (?, ?, ?)").run(level, redactLogMessage(message), new Date().toISOString());
}

function redactLogMessage(message: string) {
  return message
    .replace(/\/sub\/[A-Za-z0-9_-]+\/(raw|base64)/g, "/sub/***/$1")
    .replace(/\/r\/[A-Za-z0-9_-]+/g, "/r/***")
    .replace(/[A-Za-z0-9_-]{24,}/g, "***");
}
