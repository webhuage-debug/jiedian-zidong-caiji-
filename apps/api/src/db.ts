import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import bcrypt from "bcryptjs";
import { config } from "./config.js";
import { schemaSql } from "./schema.js";

export const db = new Database(config.DATABASE_PATH);
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

export function initializeDatabase() {
  fs.mkdirSync(path.dirname(config.DATABASE_PATH), { recursive: true });
  fs.mkdirSync(config.EXPORT_DIR, { recursive: true });
  db.exec(schemaSql);
  ensureInitialAdmin();
}

function ensureInitialAdmin() {
  const existing = db.prepare("SELECT id FROM admin_users LIMIT 1").get();
  if (existing) return;

  const now = new Date().toISOString();
  const passwordHash = bcrypt.hashSync(config.ADMIN_PASSWORD, 12);
  db.prepare(
    `INSERT INTO admin_users (username, password_hash, created_at, updated_at)
     VALUES (@username, @passwordHash, @now, @now)`
  ).run({
    username: config.ADMIN_USERNAME,
    passwordHash,
    now
  });
}
