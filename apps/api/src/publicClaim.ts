import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import bcrypt from "bcryptjs";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { z } from "zod";
import { config } from "./config.js";
import { db } from "./db.js";

const unlockCookiePrefix = "pna_claim_";
const downloadBuckets = new Map<string, { count: number; resetAt: number }>();
const verifyBuckets = new Map<string, { wrongCount: number; resetAt: number; lockedUntil?: number }>();

type BatchRow = {
  id: number;
  batch_code: string;
  name: string;
  description?: string;
  status: string;
  passphrase_hash: string | null;
  package_path: string;
  public_slug: string;
  requires_passphrase: number;
  allow_public_claim: number;
  expires_at?: string | null;
  max_downloads?: number | null;
  ip_download_limit?: number | null;
  wrong_passphrase_limit?: number | null;
  created_at: string;
};

export function registerPublicClaimRoutes(app: FastifyInstance) {
  app.get("/api/public/claim/:slug", async (request, reply) => {
    reply.header("X-Robots-Tag", "noindex, nofollow");
    const { slug } = request.params as { slug: string };
    const batch = getPublicBatch(slug);
    if (!batch) return { found: false };
    recordPublicEvent(batch.id, "view", request);
    incrementStat(batch.id, "view_count");
    return {
      found: true,
      batch: publicBatchInfo(batch),
      unlocked: !batch.requires_passphrase || isUnlocked(request, slug)
    };
  });

  app.post("/api/public/claim/:slug/verify", async (request, reply) => {
    reply.header("X-Robots-Tag", "noindex, nofollow");
    const { slug } = request.params as { slug: string };
    const body = z.object({ passphrase: z.string().max(128).default("") }).parse(request.body);
    const batch = getPublicBatch(slug);
    if (!batch) return reply.code(404).send({ ok: false, message: "领取已关闭" });
    if (!batch.requires_passphrase) {
      incrementStat(batch.id, "unlock_count");
      setUnlockCookie(reply, slug);
      return { ok: true, downloadUrl: `/api/public/claim/${slug}/download` };
    }
    if (!allowVerify(request, slug, batch)) return reply.code(429).send({ ok: false, message: "请求过于频繁，请稍后再试" });

    incrementStat(batch.id, "passphrase_attempt_count");
    recordPublicEvent(batch.id, "passphrase_attempt", request);
    const valid = batch.passphrase_hash ? await bcrypt.compare(body.passphrase, batch.passphrase_hash) : false;
    if (!valid) {
      recordWrongPassphrase(request, slug, batch);
      incrementStat(batch.id, "passphrase_wrong_count");
      recordPublicEvent(batch.id, "passphrase_wrong", request);
      return reply.code(401).send({ ok: false, message: "口令错误" });
    }

    clearVerifyFailure(request, slug);
    incrementStat(batch.id, "passphrase_correct_count");
    incrementStat(batch.id, "unlock_count");
    recordPublicEvent(batch.id, "passphrase_correct", request);
    setUnlockCookie(reply, slug);
    return { ok: true, downloadUrl: `/api/public/claim/${slug}/download` };
  });

  app.get("/api/public/claim/:slug/download", async (request, reply) => {
    reply.header("X-Robots-Tag", "noindex, nofollow");
    const { slug } = request.params as { slug: string };
    const batch = getPublicBatch(slug);
    if (!batch) return reply.code(404).send({ message: "领取已关闭" });
    if (batch.requires_passphrase && !isUnlocked(request, slug)) return reply.code(401).send({ message: "请先输入正确口令" });
    if (isTotalDownloadExceeded(batch)) return reply.code(429).send({ message: "下载次数已达上限" });
    if (!allowDownload(request, batch)) return reply.code(429).send({ message: "请求过于频繁，请稍后再试" });
    if (!isPackagePathAllowed(batch.package_path) || !fs.existsSync(batch.package_path)) {
      return reply.code(404).send({ message: "领取已关闭" });
    }

    incrementStat(batch.id, "download_count");
    recordPublicEvent(batch.id, "download", request);
    const fileName = `${batch.batch_code}.zip`;
    reply.header("Content-Type", "application/zip");
    reply.header("Content-Disposition", `attachment; filename="${encodeURIComponent(fileName)}"`);
    return reply.send(fs.createReadStream(batch.package_path));
  });

  app.post("/api/public/claim/:slug/feedback", async (request, reply) => {
    reply.header("X-Robots-Tag", "noindex, nofollow");
    const { slug } = request.params as { slug: string };
    const batch = getPublicBatch(slug);
    if (!batch) return reply.code(404).send({ ok: false, message: "领取已关闭" });

    const body = z
      .object({
        region: z.string().max(80).optional().default(""),
        carrier: z.string().max(80).optional().default(""),
        device: z.string().max(80).optional().default(""),
        clientApp: z.string().max(80).optional().default(""),
        issueType: z
          .enum(["connection_failed", "high_latency", "youtube_stuck", "chatgpt_failed", "tiktok_failed", "partial_available", "all_failed", "import_help", "download_failed", "other"])
          .optional()
          .default("other"),
        isUsable: z.boolean().optional(),
        note: z.string().max(200).optional().default("")
      })
      .parse(request.body);

    const sourcePlatform = typeof request.query === "object" && request.query ? (request.query as { from?: string }).from : undefined;
    db.prepare(
      `INSERT INTO feedback (batch_id, region, carrier, device, client_app, is_usable, issue_type, source_platform, note, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      batch.id,
      body.region,
      body.carrier,
      body.device,
      body.clientApp,
      body.isUsable === undefined ? null : body.isUsable ? 1 : 0,
      body.issueType,
      sourcePlatform ?? null,
      body.note,
      new Date().toISOString()
    );
    incrementStat(batch.id, "feedback_count");
    recordPublicEvent(batch.id, "feedback", request);
    return { ok: true };
  });

}

function getPublicBatch(slug: string) {
  const batch = db
    .prepare(
      `SELECT id, batch_code, name, description, status, passphrase_hash,
              package_path, public_slug, requires_passphrase, allow_public_claim, expires_at, max_downloads,
              ip_download_limit, wrong_passphrase_limit, created_at
       FROM export_batches
       WHERE public_slug = ?`
    )
    .get(slug) as BatchRow | undefined;
  if (!batch) return null;
  if (batch.status !== "published") return null;
  if (!batch.allow_public_claim) return null;
  if (batch.expires_at && new Date(batch.expires_at).getTime() <= Date.now()) {
    db.prepare("UPDATE export_batches SET status = 'expired', updated_at = ? WHERE id = ?").run(new Date().toISOString(), batch.id);
    return null;
  }
  return batch;
}

function publicBatchInfo(batch: BatchRow) {
  return {
    title: batch.name || "节点包领取",
    description: batch.description || "输入本期口令后即可领取节点包。",
    expiresAt: batch.expires_at ?? null
  };
}

function setUnlockCookie(reply: FastifyReply, slug: string) {
  reply.setCookie(unlockCookieName(slug), `unlocked:${slug}`, {
    httpOnly: true,
    sameSite: "lax",
    secure: config.COOKIE_SECURE,
    path: `/`,
    signed: true,
    maxAge: 60 * 60 * 2
  });
}

function isUnlocked(request: FastifyRequest, slug: string) {
  const raw = request.cookies[unlockCookieName(slug)];
  if (!raw) return false;
  const unsigned = request.unsignCookie(raw);
  return unsigned.valid && unsigned.value === `unlocked:${slug}`;
}

function unlockCookieName(slug: string) {
  return `${unlockCookiePrefix}${slug}`;
}

function incrementStat(batchId: number, field: string) {
  const allowed = new Set([
    "view_count",
    "passphrase_attempt_count",
    "passphrase_correct_count",
    "passphrase_wrong_count",
    "unlock_count",
    "download_count",
    "feedback_count"
  ]);
  if (!allowed.has(field)) return;
  db.prepare(`UPDATE batch_stats SET ${field} = ${field} + 1, updated_at = ? WHERE batch_id = ?`).run(new Date().toISOString(), batchId);
}

function recordPublicEvent(batchId: number, eventType: string, request: FastifyRequest) {
  const sourcePlatform = typeof request.query === "object" && request.query ? (request.query as { from?: string }).from : undefined;
  db.prepare(
    `INSERT INTO public_events (batch_id, event_type, source_platform, ip_hash, user_agent, created_at)
     VALUES (?, ?, ?, ?, ?, ?)`
  ).run(batchId, eventType, sourcePlatform ?? null, hashIp(request.ip), request.headers["user-agent"] ?? "", new Date().toISOString());
}

function hashIp(ip: string) {
  return crypto.createHmac("sha256", config.SESSION_SECRET).update(ip).digest("hex");
}

function allowVerify(request: FastifyRequest, slug: string, batch: BatchRow) {
  const key = verifyKey(request, slug);
  const now = Date.now();
  const existing = verifyBuckets.get(key);
  if (!existing || existing.resetAt <= now) return true;
  if (existing.lockedUntil && existing.lockedUntil > now) return false;
  return existing.wrongCount < (batch.wrong_passphrase_limit ?? 8);
}

function recordWrongPassphrase(request: FastifyRequest, slug: string, batch: BatchRow) {
  const key = verifyKey(request, slug);
  const now = Date.now();
  const existing = verifyBuckets.get(key);
  const wrongCount = existing && existing.resetAt > now ? existing.wrongCount + 1 : 1;
  const limit = batch.wrong_passphrase_limit ?? 8;
  verifyBuckets.set(key, {
    wrongCount,
    resetAt: now + 60 * 60 * 1000,
    lockedUntil: wrongCount >= limit ? now + 15 * 60 * 1000 : undefined
  });
}

function clearVerifyFailure(request: FastifyRequest, slug: string) {
  verifyBuckets.delete(verifyKey(request, slug));
}

function verifyKey(request: FastifyRequest, slug: string) {
  return `${slug}:${hashIp(request.ip)}:verify`;
}

function isTotalDownloadExceeded(batch: BatchRow) {
  if (!batch.max_downloads) return false;
  const row = db.prepare("SELECT download_count FROM batch_stats WHERE batch_id = ?").get(batch.id) as { download_count: number } | undefined;
  return (row?.download_count ?? 0) >= batch.max_downloads;
}

function allowDownload(request: FastifyRequest, batch: BatchRow) {
  const key = `${batch.public_slug}:${hashIp(request.ip)}:download`;
  const now = Date.now();
  const existing = downloadBuckets.get(key);
  if (!existing || existing.resetAt <= now) {
    downloadBuckets.set(key, { count: 1, resetAt: now + 24 * 60 * 60 * 1000 });
    return true;
  }
  const limit = Math.min(batch.ip_download_limit ?? 3, config.DOWNLOAD_RATE_LIMIT_PER_MINUTE);
  if (existing.count >= limit) return false;
  existing.count += 1;
  return true;
}

function isPackagePathAllowed(packagePath: string) {
  const resolved = path.resolve(packagePath);
  return resolved.startsWith(config.EXPORT_DIR + path.sep);
}
