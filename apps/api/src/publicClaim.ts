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

type BatchRow = {
  id: number;
  batch_code: string;
  name: string;
  description?: string;
  status: string;
  passphrase_hash: string;
  node_count: number;
  package_path: string;
  public_slug: string;
  expires_at?: string;
  created_at: string;
};

export function registerPublicClaimRoutes(app: FastifyInstance) {
  app.get("/api/public/batches/:slug", async (request) => {
    const { slug } = request.params as { slug: string };
    const batch = getPublicBatch(slug);
    if (!batch) return { found: false };
    recordPublicEvent(batch.id, "view", request);
    incrementStat(batch.id, "view_count");
    return {
      found: true,
      batch: publicBatchInfo(batch),
      unlocked: isUnlocked(request, slug)
    };
  });

  app.post("/api/public/batches/:slug/verify", async (request, reply) => {
    const { slug } = request.params as { slug: string };
    const body = z.object({ passphrase: z.string().min(1) }).parse(request.body);
    const batch = getPublicBatch(slug);
    if (!batch) {
      return reply.code(404).send({ ok: false, message: "领取批次不存在。" });
    }

    incrementStat(batch.id, "passphrase_attempt_count");
    recordPublicEvent(batch.id, "passphrase_attempt", request);
    const valid = await bcrypt.compare(body.passphrase, batch.passphrase_hash);
    if (!valid) {
      incrementStat(batch.id, "passphrase_wrong_count");
      recordPublicEvent(batch.id, "passphrase_wrong", request);
      return reply.code(401).send({ ok: false, message: "口令不正确。" });
    }

    incrementStat(batch.id, "passphrase_correct_count");
    incrementStat(batch.id, "unlock_count");
    recordPublicEvent(batch.id, "passphrase_correct", request);
    setUnlockCookie(reply, slug);
    return { ok: true, batch: publicBatchInfo(batch), downloadUrl: `/api/public/batches/${slug}/download` };
  });

  app.get("/api/public/batches/:slug/download", async (request, reply) => {
    const { slug } = request.params as { slug: string };
    const batch = getPublicBatch(slug);
    if (!batch) {
      return reply.code(404).send({ message: "领取批次不存在。" });
    }
    if (!isUnlocked(request, slug)) {
      return reply.code(401).send({ message: "请先输入正确口令。" });
    }
    if (!allowDownload(request, slug)) {
      return reply.code(429).send({ message: "下载过于频繁，请稍后再试。" });
    }
    if (!isPackagePathAllowed(batch.package_path) || !fs.existsSync(batch.package_path)) {
      return reply.code(404).send({ message: "节点包不存在。" });
    }

    incrementStat(batch.id, "download_count");
    recordPublicEvent(batch.id, "download", request);
    const fileName = `${batch.batch_code}.zip`;
    reply.header("Content-Type", "application/zip");
    reply.header("Content-Disposition", `attachment; filename="${encodeURIComponent(fileName)}"`);
    return reply.send(fs.createReadStream(batch.package_path));
  });

  app.post("/api/public/batches/:slug/feedback", async (request, reply) => {
    const { slug } = request.params as { slug: string };
    const batch = getPublicBatch(slug);
    if (!batch) {
      return reply.code(404).send({ ok: false, message: "领取批次不存在。" });
    }

    const body = z
      .object({
        region: z.string().max(80).optional().default(""),
        carrier: z.string().max(80).optional().default(""),
        device: z.string().max(80).optional().default(""),
        clientApp: z.string().max(80).optional().default(""),
        isUsable: z.boolean().optional(),
        note: z.string().max(1000).optional().default("")
      })
      .parse(request.body);

    db.prepare(
      `INSERT INTO feedback (batch_id, region, carrier, device, client_app, is_usable, note, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      batch.id,
      body.region,
      body.carrier,
      body.device,
      body.clientApp,
      body.isUsable === undefined ? null : body.isUsable ? 1 : 0,
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
      `SELECT id, batch_code, name, description, status, passphrase_hash, node_count,
              package_path, public_slug, expires_at, created_at
       FROM export_batches
       WHERE public_slug = ?`
    )
    .get(slug) as BatchRow | undefined;
  if (!batch) return null;
  if (batch.status !== "published") return null;
  if (batch.expires_at && new Date(batch.expires_at).getTime() <= Date.now()) {
    db.prepare("UPDATE export_batches SET status = 'expired', updated_at = ? WHERE id = ?").run(new Date().toISOString(), batch.id);
    return null;
  }
  return batch;
}

function publicBatchInfo(batch: BatchRow) {
  return {
    batchCode: batch.batch_code,
    name: batch.name,
    description: batch.description ?? "",
    nodeCount: batch.node_count,
    expiresAt: batch.expires_at ?? null,
    createdAt: batch.created_at
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
  ).run(
    batchId,
    eventType,
    sourcePlatform ?? null,
    hashIp(request.ip),
    request.headers["user-agent"] ?? "",
    new Date().toISOString()
  );
}

function hashIp(ip: string) {
  return crypto.createHmac("sha256", config.SESSION_SECRET).update(ip).digest("hex");
}

function allowDownload(request: FastifyRequest, slug: string) {
  const key = `${slug}:${hashIp(request.ip)}`;
  const now = Date.now();
  const existing = downloadBuckets.get(key);
  if (!existing || existing.resetAt <= now) {
    downloadBuckets.set(key, { count: 1, resetAt: now + 60_000 });
    return true;
  }
  if (existing.count >= config.DOWNLOAD_RATE_LIMIT_PER_MINUTE) {
    return false;
  }
  existing.count += 1;
  return true;
}

function isPackagePathAllowed(packagePath: string) {
  const resolved = path.resolve(packagePath);
  return resolved.startsWith(config.EXPORT_DIR + path.sep);
}
