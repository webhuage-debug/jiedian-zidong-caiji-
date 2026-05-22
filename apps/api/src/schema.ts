export const schemaSql = `
CREATE TABLE IF NOT EXISTS admin_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  admin_user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  user_agent TEXT,
  ip_address TEXT
);

CREATE TABLE IF NOT EXISTS auth_failures (
  key TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  ip_address TEXT NOT NULL,
  failure_count INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  last_failure_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  last_checked_at TEXT,
  next_allowed_at TEXT,
  last_error TEXT,
  content_hash TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_hash TEXT NOT NULL UNIQUE,
  content TEXT NOT NULL,
  protocol TEXT NOT NULL,
  source_id INTEGER REFERENCES node_sources(id) ON DELETE SET NULL,
  source_url TEXT,
  source_type TEXT,
  collected_at TEXT NOT NULL,
  last_tested_at TEXT,
  latency_ms INTEGER,
  status TEXT NOT NULL DEFAULT 'pending_test',
  failure_reason TEXT,
  exported_at TEXT,
  export_batch_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_status_latency ON nodes(status, latency_ms);
CREATE INDEX IF NOT EXISTS idx_nodes_protocol ON nodes(protocol);
CREATE INDEX IF NOT EXISTS idx_nodes_source_type ON nodes(source_type);

CREATE TABLE IF NOT EXISTS collection_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  discovered_sources INTEGER NOT NULL DEFAULT 0,
  fetched_sources INTEGER NOT NULL DEFAULT 0,
  raw_nodes INTEGER NOT NULL DEFAULT 0,
  deduped_nodes INTEGER NOT NULL DEFAULT 0,
  inserted_nodes INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS collection_run_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collection_run_id INTEGER NOT NULL REFERENCES collection_runs(id) ON DELETE CASCADE,
  source_id INTEGER REFERENCES node_sources(id) ON DELETE SET NULL,
  url TEXT NOT NULL,
  status TEXT NOT NULL,
  raw_nodes INTEGER NOT NULL DEFAULT 0,
  inserted_nodes INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  tested_nodes INTEGER NOT NULL DEFAULT 0,
  passed_nodes INTEGER NOT NULL DEFAULT 0,
  failed_nodes INTEGER NOT NULL DEFAULT 0,
  removed_nodes INTEGER NOT NULL DEFAULT 0,
  min_latency_ms INTEGER,
  avg_latency_ms INTEGER,
  max_latency_ms INTEGER,
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS export_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  passphrase_hash TEXT,
  node_count INTEGER NOT NULL DEFAULT 0,
  package_path TEXT,
  public_slug TEXT NOT NULL UNIQUE,
  published_at TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_stats (
  batch_id INTEGER PRIMARY KEY REFERENCES export_batches(id) ON DELETE CASCADE,
  view_count INTEGER NOT NULL DEFAULT 0,
  passphrase_attempt_count INTEGER NOT NULL DEFAULT 0,
  passphrase_correct_count INTEGER NOT NULL DEFAULT 0,
  passphrase_wrong_count INTEGER NOT NULL DEFAULT 0,
  unlock_count INTEGER NOT NULL DEFAULT 0,
  download_count INTEGER NOT NULL DEFAULT 0,
  feedback_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER REFERENCES export_batches(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  source_platform TEXT,
  ip_hash TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER REFERENCES export_batches(id) ON DELETE SET NULL,
  region TEXT,
  carrier TEXT,
  device TEXT,
  client_app TEXT,
  is_usable INTEGER,
  note TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  context_json TEXT,
  created_at TEXT NOT NULL
);
`;
