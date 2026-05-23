import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import bcrypt from "bcryptjs";
import { nanoid } from "nanoid";
import { z } from "zod";
import { config } from "./config.js";
import { db } from "./db.js";

const sessionCookie = "pna_session";

type AdminUser = {
  id: number;
  username: string;
  password_hash: string;
};

declare module "fastify" {
  interface FastifyRequest {
    adminUser?: { id: number; username: string };
  }
}

export function registerAuthRoutes(app: FastifyInstance) {
  app.post("/api/auth/login", async (request, reply) => {
    const body = z.object({ username: z.string().min(1), password: z.string().min(1) }).parse(request.body);
    const ip = request.ip;
    const key = failureKey(body.username, ip);

    const failure = getFailure(key);
    if (failure?.locked_until && new Date(failure.locked_until).getTime() > Date.now()) {
      return reply.code(423).send({ message: "登录失败次数过多，请稍后再试。" });
    }

    const user = db.prepare("SELECT * FROM admin_users WHERE username = ?").get(body.username) as AdminUser | undefined;
    const valid = user ? await bcrypt.compare(body.password, user.password_hash) : false;

    if (!user || !valid) {
      recordFailure(key, body.username, ip);
      return reply.code(401).send({ message: "账号或密码错误。" });
    }

    clearFailure(key);
    const sessionId = createSession(user.id, request);
    db.prepare("UPDATE admin_users SET last_login_at = ? WHERE id = ?").run(new Date().toISOString(), user.id);
    setSessionCookie(reply, sessionId);
    return { user: { id: user.id, username: user.username } };
  });

  app.post("/api/auth/logout", { preHandler: requireAdmin }, async (request, reply) => {
    const sessionId = request.cookies[sessionCookie];
    if (sessionId) {
      db.prepare("DELETE FROM sessions WHERE id = ?").run(sessionId);
    }
    reply.clearCookie(sessionCookie, cookieOptions());
    return { ok: true };
  });

  app.get("/api/auth/status", async (request) => {
    const user = getUserFromSession(request);
    return { authenticated: Boolean(user), user };
  });

  app.post("/api/auth/change-password", { preHandler: requireAdmin }, async (request) => {
    const body = z
      .object({
        currentPassword: z.string().min(1),
        newPassword: z.string().min(10)
      })
      .parse(request.body);

    const user = db.prepare("SELECT * FROM admin_users WHERE id = ?").get(request.adminUser!.id) as AdminUser;
    const valid = await bcrypt.compare(body.currentPassword, user.password_hash);
    if (!valid) {
      return { ok: false, message: "当前密码不正确。" };
    }

    const passwordHash = await bcrypt.hash(body.newPassword, 12);
    db.prepare("UPDATE admin_users SET password_hash = ?, updated_at = ? WHERE id = ?").run(
      passwordHash,
      new Date().toISOString(),
      user.id
    );
    db.prepare("DELETE FROM sessions WHERE admin_user_id = ? AND id != ?").run(user.id, request.cookies[sessionCookie]);
    return { ok: true };
  });
}

export async function requireAdmin(request: FastifyRequest, reply: FastifyReply) {
  const user = getUserFromSession(request);
  if (!user) {
    return reply.code(401).send({ message: "请先登录后台。" });
  }
  request.adminUser = user;
}

function getUserFromSession(request: FastifyRequest) {
  const sessionId = request.cookies[sessionCookie];
  if (!sessionId) return null;

  const row = db
    .prepare(
      `SELECT sessions.id, sessions.expires_at, admin_users.id AS user_id, admin_users.username
       FROM sessions
       JOIN admin_users ON admin_users.id = sessions.admin_user_id
       WHERE sessions.id = ?`
    )
    .get(sessionId) as { id: string; expires_at: string; user_id: number; username: string } | undefined;

  if (!row) return null;
  if (new Date(row.expires_at).getTime() <= Date.now()) {
    db.prepare("DELETE FROM sessions WHERE id = ?").run(sessionId);
    return null;
  }

  db.prepare("UPDATE sessions SET last_seen_at = ? WHERE id = ?").run(new Date().toISOString(), sessionId);
  return { id: row.user_id, username: row.username };
}

function createSession(adminUserId: number, request: FastifyRequest) {
  const sessionId = nanoid(48);
  const now = new Date();
  const expiresAt = new Date(now.getTime() + config.SESSION_TTL_MS);
  db.prepare(
    `INSERT INTO sessions (id, admin_user_id, created_at, expires_at, last_seen_at, user_agent, ip_address)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(sessionId, adminUserId, now.toISOString(), expiresAt.toISOString(), now.toISOString(), request.headers["user-agent"] ?? "", request.ip);
  return sessionId;
}

function setSessionCookie(reply: FastifyReply, sessionId: string) {
  reply.setCookie(sessionCookie, sessionId, cookieOptions());
}

function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: config.COOKIE_SECURE,
    path: "/",
    maxAge: Math.floor(config.SESSION_TTL_MS / 1000)
  };
}

function failureKey(username: string, ip: string) {
  return `${username.toLowerCase()}|${ip}`;
}

function getFailure(key: string) {
  return db.prepare("SELECT * FROM auth_failures WHERE key = ?").get(key) as
    | { failure_count: number; locked_until?: string }
    | undefined;
}

function recordFailure(key: string, username: string, ip: string) {
  const now = new Date().toISOString();
  const existing = getFailure(key);
  const failureCount = (existing?.failure_count ?? 0) + 1;
  const lockedUntil = failureCount >= config.LOGIN_MAX_FAILURES ? new Date(Date.now() + config.LOGIN_LOCK_MS).toISOString() : null;

  db.prepare(
    `INSERT INTO auth_failures (key, username, ip_address, failure_count, locked_until, last_failure_at)
     VALUES (?, ?, ?, ?, ?, ?)
     ON CONFLICT(key) DO UPDATE SET
       failure_count = excluded.failure_count,
       locked_until = excluded.locked_until,
       last_failure_at = excluded.last_failure_at`
  ).run(key, username, ip, failureCount, lockedUntil, now);
}

function clearFailure(key: string) {
  db.prepare("DELETE FROM auth_failures WHERE key = ?").run(key);
}
