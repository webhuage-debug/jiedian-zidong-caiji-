import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import bcrypt from "bcryptjs";
import { config } from "./config.js";
import { schemaSql } from "./schema.js";

fs.mkdirSync(path.dirname(config.DATABASE_PATH), { recursive: true });
fs.mkdirSync(config.EXPORT_DIR, { recursive: true });
fs.mkdirSync(config.SUB_CACHE_DIR, { recursive: true });

export const db = new Database(config.DATABASE_PATH);
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

export function initializeDatabase() {
  db.exec(schemaSql);
  runLightweightMigrations();
  ensureInitialAdmin();
}

function runLightweightMigrations() {
  db.prepare(
    `CREATE TABLE IF NOT EXISTS export_batch_nodes (
      batch_id INTEGER NOT NULL REFERENCES export_batches(id) ON DELETE CASCADE,
      node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
      created_at TEXT NOT NULL,
      PRIMARY KEY (batch_id, node_id)
    )`
  ).run();

  db.prepare(
    `CREATE TABLE IF NOT EXISTS subscription_activities (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      video_note TEXT,
      status TEXT NOT NULL DEFAULT 'draft',
      claim_slug TEXT NOT NULL UNIQUE,
      subscription_token TEXT NOT NULL UNIQUE,
      passphrase_hash TEXT,
      starts_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      output_count INTEGER NOT NULL DEFAULT 10,
      target_latency_ms INTEGER NOT NULL DEFAULT 200,
      warning_latency_ms INTEGER NOT NULL DEFAULT 300,
      remove_latency_ms INTEGER NOT NULL DEFAULT 500,
      health_check_interval_minutes INTEGER NOT NULL DEFAULT 5,
      last_health_check_at TEXT,
      last_cache_generated_at TEXT,
      last_replacement_count INTEGER NOT NULL DEFAULT 0,
      risk_status TEXT NOT NULL DEFAULT 'normal',
      risk_message TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )`
  ).run();

  db.prepare(
    `CREATE TABLE IF NOT EXISTS subscription_activity_nodes (
      activity_id INTEGER NOT NULL REFERENCES subscription_activities(id) ON DELETE CASCADE,
      node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
      region_group TEXT,
      added_at TEXT NOT NULL,
      last_checked_at TEXT,
      consecutive_failures INTEGER NOT NULL DEFAULT 0,
      consecutive_high_latency INTEGER NOT NULL DEFAULT 0,
      replaced_at TEXT,
      PRIMARY KEY (activity_id, node_id)
    )`
  ).run();

  db.prepare(
    `CREATE TABLE IF NOT EXISTS subscription_stats (
      activity_id INTEGER PRIMARY KEY REFERENCES subscription_activities(id) ON DELETE CASCADE,
      view_count INTEGER NOT NULL DEFAULT 0,
      passphrase_attempt_count INTEGER NOT NULL DEFAULT 0,
      passphrase_correct_count INTEGER NOT NULL DEFAULT 0,
      passphrase_wrong_count INTEGER NOT NULL DEFAULT 0,
      unlock_count INTEGER NOT NULL DEFAULT 0,
      raw_access_count INTEGER NOT NULL DEFAULT 0,
      base64_access_count INTEGER NOT NULL DEFAULT 0,
      feedback_count INTEGER NOT NULL DEFAULT 0,
      active_ip_count INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL
    )`
  ).run();

  db.prepare(
    `CREATE TABLE IF NOT EXISTS subscription_access_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      activity_id INTEGER REFERENCES subscription_activities(id) ON DELETE SET NULL,
      event_type TEXT NOT NULL,
      source_platform TEXT,
      ip_hash TEXT,
      user_agent TEXT,
      created_at TEXT NOT NULL
    )`
  ).run();

  const sourceColumns = db.prepare("PRAGMA table_info(node_sources)").all() as Array<{ name: string }>;
  if (!sourceColumns.some((column) => column.name === "content_hash")) {
    db.prepare("ALTER TABLE node_sources ADD COLUMN content_hash TEXT").run();
  }

  const nodeColumns = db.prepare("PRAGMA table_info(nodes)").all() as Array<{ name: string }>;
  addColumn(nodeColumns, "nodes", "real_latency_ms", "INTEGER");
  addColumn(nodeColumns, "nodes", "real_status", "TEXT");
  addColumn(nodeColumns, "nodes", "real_tested_at", "TEXT");
  addColumn(nodeColumns, "nodes", "test_method", "TEXT NOT NULL DEFAULT 'tcp'");
  addColumn(nodeColumns, "nodes", "success_count", "INTEGER NOT NULL DEFAULT 0");
  addColumn(nodeColumns, "nodes", "failure_count", "INTEGER NOT NULL DEFAULT 0");
  addColumn(nodeColumns, "nodes", "quality_tier", "TEXT");
  addColumn(nodeColumns, "nodes", "eligible_for_package", "INTEGER NOT NULL DEFAULT 1");

  const testRunColumns = db.prepare("PRAGMA table_info(test_runs)").all() as Array<{ name: string }>;
  addColumn(testRunColumns, "test_runs", "test_method", "TEXT NOT NULL DEFAULT 'tcp'");

  const batchColumns = db.prepare("PRAGMA table_info(export_batches)").all() as Array<{ name: string }>;
  if (batchColumns.length) {
    addColumn(batchColumns, "export_batches", "text_file_path", "TEXT");
    addColumn(batchColumns, "export_batches", "clash_file_path", "TEXT");
    addColumn(batchColumns, "export_batches", "singbox_file_path", "TEXT");
    addColumn(batchColumns, "export_batches", "readme_file_path", "TEXT");
    addColumn(batchColumns, "export_batches", "export_options_json", "TEXT");
    addColumn(batchColumns, "export_batches", "quality_tier", "TEXT");
    addColumn(batchColumns, "export_batches", "requires_passphrase", "INTEGER NOT NULL DEFAULT 1");
    addColumn(batchColumns, "export_batches", "allow_public_claim", "INTEGER NOT NULL DEFAULT 1");
    addColumn(batchColumns, "export_batches", "allow_automation", "INTEGER NOT NULL DEFAULT 0");
    addColumn(batchColumns, "export_batches", "allow_direct_download", "INTEGER NOT NULL DEFAULT 0");
    addColumn(batchColumns, "export_batches", "allow_hermes_file", "INTEGER NOT NULL DEFAULT 0");
    addColumn(batchColumns, "export_batches", "allow_hermes_link", "INTEGER NOT NULL DEFAULT 0");
    addColumn(batchColumns, "export_batches", "last_tested_at", "TEXT");
    addColumn(batchColumns, "export_batches", "test_method", "TEXT");
    addColumn(batchColumns, "export_batches", "pass_rate", "INTEGER");
    addColumn(batchColumns, "export_batches", "max_downloads", "INTEGER");
    addColumn(batchColumns, "export_batches", "ip_download_limit", "INTEGER NOT NULL DEFAULT 3");
    addColumn(batchColumns, "export_batches", "wrong_passphrase_limit", "INTEGER NOT NULL DEFAULT 8");
  }

  const feedbackColumns = db.prepare("PRAGMA table_info(feedback)").all() as Array<{ name: string }>;
  if (feedbackColumns.length) {
    if (!feedbackColumns.some((column) => column.name === "subscription_activity_id")) {
      db.prepare("ALTER TABLE feedback ADD COLUMN subscription_activity_id INTEGER REFERENCES subscription_activities(id) ON DELETE SET NULL").run();
    }
    if (!feedbackColumns.some((column) => column.name === "subscription_token")) {
      db.prepare("ALTER TABLE feedback ADD COLUMN subscription_token TEXT").run();
    }
    if (!feedbackColumns.some((column) => column.name === "issue_type")) {
      db.prepare("ALTER TABLE feedback ADD COLUMN issue_type TEXT").run();
    }
    if (!feedbackColumns.some((column) => column.name === "source_platform")) {
      db.prepare("ALTER TABLE feedback ADD COLUMN source_platform TEXT").run();
    }
    if (!feedbackColumns.some((column) => column.name === "process_status")) {
      db.prepare("ALTER TABLE feedback ADD COLUMN process_status TEXT NOT NULL DEFAULT 'pending'").run();
    }
    if (!feedbackColumns.some((column) => column.name === "process_note")) {
      db.prepare("ALTER TABLE feedback ADD COLUMN process_note TEXT").run();
    }
  }

  const subscriptionColumns = db.prepare("PRAGMA table_info(subscription_activities)").all() as Array<{ name: string }>;
  if (subscriptionColumns.length) {
    if (!subscriptionColumns.some((column) => column.name === "last_replacement_count")) {
      db.prepare("ALTER TABLE subscription_activities ADD COLUMN last_replacement_count INTEGER NOT NULL DEFAULT 0").run();
    }
  }
}

function addColumn(columns: Array<{ name: string }>, table: string, name: string, definition: string) {
  if (!columns.some((column) => column.name === name)) {
    db.prepare(`ALTER TABLE ${table} ADD COLUMN ${name} ${definition}`).run();
    columns.push({ name });
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
