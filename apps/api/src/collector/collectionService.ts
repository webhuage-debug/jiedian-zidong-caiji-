import { config } from "../config.js";
import { db } from "../db.js";
import { discoverPublicSources, type DiscoveredSource } from "./sourceDiscovery.js";
import { fetchTextWithLimit, withTimeout } from "./http.js";
import { extractNodes, sha256 } from "./nodeParser.js";

type CollectionSummary = {
  runId: number;
  discoveredSources: number;
  fetchedSources: number;
  rawNodes: number;
  dedupedNodes: number;
  insertedNodes: number;
  errorCount: number;
};

let activeRun: Promise<CollectionSummary> | null = null;

export async function runCollection() {
  if (activeRun) return activeRun;
  activeRun = runCollectionInternal().finally(() => {
    activeRun = null;
  });
  return activeRun;
}

function canStartDailyRun() {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const row = db
    .prepare("SELECT COUNT(*) AS count FROM collection_runs WHERE started_at >= ?")
    .get(since) as { count: number };
  return row.count < config.COLLECT_DAILY_MAX_RUNS;
}

async function runCollectionInternal(): Promise<CollectionSummary> {
  if (!canStartDailyRun()) {
    throw new Error("daily collection limit reached");
  }

  const startedAt = new Date().toISOString();
  const runResult = db
    .prepare("INSERT INTO collection_runs (status, started_at) VALUES ('running', ?)")
    .run(startedAt);
  const runId = Number(runResult.lastInsertRowid);

  const timeout = withTimeout();
  let discovered: DiscoveredSource[] = [];
  try {
    discovered = await discoverPublicSources(timeout.signal);
  } finally {
    timeout.done();
  }

  const allowedSources = upsertAndFilterSources(discovered);
  const summary: CollectionSummary = {
    runId,
    discoveredSources: discovered.length,
    fetchedSources: 0,
    rawNodes: 0,
    dedupedNodes: 0,
    insertedNodes: 0,
    errorCount: 0
  };

  const queue = [...allowedSources];
  const workers = Array.from({ length: Math.min(config.COLLECT_MAX_CONCURRENCY, queue.length) }, async () => {
    while (queue.length) {
      const source = queue.shift();
      if (!source) return;
      const result = await collectSource(runId, source);
      summary.fetchedSources += result.fetched ? 1 : 0;
      summary.rawNodes += result.rawNodes;
      summary.dedupedNodes += result.dedupedNodes;
      summary.insertedNodes += result.insertedNodes;
      summary.errorCount += result.error ? 1 : 0;
    }
  });

  await Promise.all(workers);

  const status = summary.errorCount > 0 && summary.fetchedSources === 0 ? "failed" : "completed";
  db.prepare(
    `UPDATE collection_runs
     SET status = ?, finished_at = ?, discovered_sources = ?, fetched_sources = ?, raw_nodes = ?,
         deduped_nodes = ?, inserted_nodes = ?, error_count = ?, summary_json = ?
     WHERE id = ?`
  ).run(
    status,
    new Date().toISOString(),
    summary.discoveredSources,
    summary.fetchedSources,
    summary.rawNodes,
    summary.dedupedNodes,
    summary.insertedNodes,
    summary.errorCount,
    JSON.stringify(summary),
    runId
  );

  return summary;
}

function upsertAndFilterSources(sources: DiscoveredSource[]) {
  const now = new Date().toISOString();
  const result: Array<DiscoveredSource & { sourceId: number }> = [];

  for (const source of sources) {
    db.prepare(
      `INSERT INTO node_sources (url, source_type, status, created_at, updated_at)
       VALUES (?, ?, 'pending', ?, ?)
       ON CONFLICT(url) DO UPDATE SET source_type = excluded.source_type, updated_at = excluded.updated_at`
    ).run(source.url, source.sourceType, now, now);

    const row = db.prepare("SELECT id, next_allowed_at FROM node_sources WHERE url = ?").get(source.url) as {
      id: number;
      next_allowed_at?: string;
    };
    if (row.next_allowed_at && new Date(row.next_allowed_at).getTime() > Date.now()) continue;
    result.push({ ...source, sourceId: row.id });
  }

  return result;
}

async function collectSource(runId: number, source: DiscoveredSource & { sourceId: number }) {
  let lastError = "";

  for (let attempt = 0; attempt <= config.COLLECT_RETRY_COUNT; attempt += 1) {
    const timeout = withTimeout();
    try {
      const text = await fetchTextWithLimit(source.url, timeout.signal);
      timeout.done();
      return recordSourceSuccess(runId, source, text);
    } catch (error) {
      timeout.done();
      lastError = error instanceof Error ? error.message : "unknown error";
      if (attempt < config.COLLECT_RETRY_COUNT) {
        await sleep(500 * (attempt + 1));
      }
    }
  }

  recordSourceFailure(runId, source, lastError);
  return { fetched: false, rawNodes: 0, dedupedNodes: 0, insertedNodes: 0, error: lastError };
}

function recordSourceSuccess(runId: number, source: DiscoveredSource & { sourceId: number }, text: string) {
  const now = new Date().toISOString();
  const nodes = extractNodes(text);
  const unique = new Map(nodes.map((node) => [node.hash, node]));
  let insertedNodes = 0;
  const contentHash = sha256(text);

  const insertNode = db.prepare(
    `INSERT INTO nodes (node_hash, content, protocol, source_id, source_url, source_type, collected_at, status, created_at, updated_at)
     VALUES (@hash, @content, @protocol, @sourceId, @sourceUrl, @sourceType, @now, 'pending_test', @now, @now)
     ON CONFLICT(node_hash) DO NOTHING`
  );
  const updateExistingNode = db.prepare(
    `UPDATE nodes
     SET source_id = COALESCE(source_id, @sourceId),
         source_url = COALESCE(source_url, @sourceUrl),
         source_type = COALESCE(source_type, @sourceType),
         updated_at = @now
     WHERE node_hash = @hash`
  );

  const transaction = db.transaction(() => {
    for (const node of unique.values()) {
      const info = insertNode.run({
        ...node,
        sourceId: source.sourceId,
        sourceUrl: source.url,
        sourceType: source.sourceType,
        now
      });
      if (info.changes > 0) {
        insertedNodes += 1;
      } else {
        updateExistingNode.run({
          hash: node.hash,
          sourceId: source.sourceId,
          sourceUrl: source.url,
          sourceType: source.sourceType,
          now
        });
      }
    }

    db.prepare(
      `UPDATE node_sources
       SET status = 'ok', success_count = success_count + 1, last_checked_at = ?, next_allowed_at = ?,
           last_error = NULL, content_hash = ?, updated_at = ?
       WHERE id = ?`
    ).run(now, new Date(Date.now() + config.COLLECT_MIN_INTERVAL_MS).toISOString(), contentHash, now, source.sourceId);

    db.prepare(
      `INSERT INTO collection_run_sources (collection_run_id, source_id, url, status, raw_nodes, inserted_nodes, fetched_at)
       VALUES (?, ?, ?, 'ok', ?, ?, ?)`
    ).run(runId, source.sourceId, source.url, nodes.length, insertedNodes, now);
  });

  transaction();
  return {
    fetched: true,
    rawNodes: nodes.length,
    dedupedNodes: unique.size,
    insertedNodes,
    error: ""
  };
}

function recordSourceFailure(runId: number, source: DiscoveredSource & { sourceId: number }, error: string) {
  const now = new Date().toISOString();
  const cooldownMs = config.COLLECT_MIN_INTERVAL_MS * 3;
  db.prepare(
    `UPDATE node_sources
     SET status = 'failed', failure_count = failure_count + 1, last_checked_at = ?, next_allowed_at = ?,
         last_error = ?, updated_at = ?
     WHERE id = ?`
  ).run(now, new Date(Date.now() + cooldownMs).toISOString(), error, now, source.sourceId);

  db.prepare(
    `INSERT INTO collection_run_sources (collection_run_id, source_id, url, status, error, fetched_at)
     VALUES (?, ?, ?, 'failed', ?, ?)`
  ).run(runId, source.sourceId, source.url, error, now);
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
