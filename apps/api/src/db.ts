import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import bcrypt from "bcryptjs";
import { config } from "./config.js";
import { schemaSql } from "./schema.js";

fs.mkdirSync(path.dirname(config.DATABASE_PATH), { recursive: true });
fs.mkdirSync(config.EXPORT_DIR, { recursive: true });

export const db = new Database(config.DATABASE_PATH);
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

export function initializeDatabase() {
  db.exec(schemaSql);
  runLightweightMigrations();
  ensureInitialAdmin();
}

function runLightweightMigrations() {
  const sourceColumns = db.prepare("PRAGMA table_info(node_sources)").all() as Array<{ name: string }>;
  if (!sourceColumns.some((column) => column.name === "content_hash")) {
    db.prepare("ALTER TABLE node_sources ADD COLUMN content_hash TEXT").run();
  }

  const batchColumns = db.prepare("PRAGMA table_info(export_batches)").all() as Array<{ name: string }>;
  if (batchColumns.length) {
    if (!batchColumns.some((column) => column.name === "text_file_path")) {
      db.prepare("ALTER TABLE export_batches ADD COLUMN text_file_path TEXT").run();
    }
    if (!batchColumns.some((column) => column.name === "export_options_json")) {
      db.prepare("ALTER TABLE export_batches ADD COLUMN export_options_json TEXT").run();
    }
  }
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
