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
  real_latency_ms INTEGER,
  real_status TEXT,
  real_tested_at TEXT,
  test_method TEXT NOT NULL DEFAULT 'tcp',
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  quality_tier TEXT,
  eligible_for_package INTEGER NOT NULL DEFAULT 1,
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
  test_method TEXT NOT NULL DEFAULT 'tcp',
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS node_test_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  test_run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
  node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  failure_reason TEXT,
  tested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_node_test_results_node ON node_test_results(node_id, tested_at);

CREATE TABLE IF NOT EXISTS export_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  passphrase_hash TEXT,
  node_count INTEGER NOT NULL DEFAULT 0,
  text_file_path TEXT,
  clash_file_path TEXT,
  singbox_file_path TEXT,
  readme_file_path TEXT,
  package_path TEXT,
  public_slug TEXT NOT NULL UNIQUE,
  export_options_json TEXT,
  quality_tier TEXT,
  requires_passphrase INTEGER NOT NULL DEFAULT 1,
  allow_public_claim INTEGER NOT NULL DEFAULT 1,
  allow_automation INTEGER NOT NULL DEFAULT 0,
  allow_direct_download INTEGER NOT NULL DEFAULT 0,
  allow_hermes_file INTEGER NOT NULL DEFAULT 0,
  allow_hermes_link INTEGER NOT NULL DEFAULT 0,
  last_tested_at TEXT,
  test_method TEXT,
  pass_rate INTEGER,
  published_at TEXT,
  expires_at TEXT,
  max_downloads INTEGER,
  ip_download_limit INTEGER NOT NULL DEFAULT 3,
  wrong_passphrase_limit INTEGER NOT NULL DEFAULT 8,
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

CREATE TABLE IF NOT EXISTS export_batch_nodes (
  batch_id INTEGER NOT NULL REFERENCES export_batches(id) ON DELETE CASCADE,
  node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (batch_id, node_id)
);

CREATE TABLE IF NOT EXISTS subscription_activities (
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
);

CREATE TABLE IF NOT EXISTS subscription_activity_nodes (
  activity_id INTEGER NOT NULL REFERENCES subscription_activities(id) ON DELETE CASCADE,
  node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  region_group TEXT,
  added_at TEXT NOT NULL,
  last_checked_at TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  consecutive_high_latency INTEGER NOT NULL DEFAULT 0,
  replaced_at TEXT,
  PRIMARY KEY (activity_id, node_id)
);

CREATE TABLE IF NOT EXISTS subscription_stats (
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
);

CREATE TABLE IF NOT EXISTS subscription_access_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER REFERENCES subscription_activities(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  source_platform TEXT,
  ip_hash TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL
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
  subscription_activity_id INTEGER REFERENCES subscription_activities(id) ON DELETE SET NULL,
  subscription_token TEXT,
  region TEXT,
  carrier TEXT,
  device TEXT,
  client_app TEXT,
  is_usable INTEGER,
  issue_type TEXT,
  source_platform TEXT,
  process_status TEXT NOT NULL DEFAULT 'pending',
  process_note TEXT,
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
