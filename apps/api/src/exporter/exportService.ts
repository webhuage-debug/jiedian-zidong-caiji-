import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import bcrypt from "bcryptjs";
import { nanoid } from "nanoid";
import { z } from "zod";
import { config } from "../config.js";
import { db } from "../db.js";

const execFileAsync = promisify(execFile);

export const createExportSchema = z.object({
  name: z.string().min(1).max(120),
  description: z.string().max(1000).optional().default(""),
  count: z.coerce.number().int().positive().max(1000).default(10),
  minLatencyMs: z.coerce.number().int().nonnegative().optional(),
  maxLatencyMs: z.coerce.number().int().positive().optional(),
  protocol: z.string().optional(),
  qualityTier: z.enum(["high", "premium", "community", "backup"]).optional(),
  realOnly: z.boolean().default(false),
  sort: z.enum(["latency_asc", "latency_desc", "collected_desc"]).default("latency_asc"),
  includeExported: z.boolean().default(false),
  passphrase: z.string().max(128).optional().default(""),
  requiresPassphrase: z.boolean().default(true),
  allowPublicClaim: z.boolean().default(true),
  allowAutomation: z.boolean().default(false),
  allowDirectDownload: z.boolean().default(false),
  allowHermesFile: z.boolean().default(false),
  allowHermesLink: z.boolean().default(false),
  expiresAt: z.string().datetime().optional(),
  publish: z.boolean().default(false),
  maxDownloads: z.coerce.number().int().positive().optional(),
  ipDownloadLimit: z.coerce.number().int().positive().max(100).default(3),
  wrongPassphraseLimit: z.coerce.number().int().positive().max(100).default(8)
});

type CreateExportInput = z.infer<typeof createExportSchema>;

type ExportNode = {
  id: number;
  content: string;
  protocol: string;
  latency_ms: number | null;
  real_latency_ms?: number | null;
  last_tested_at?: string | null;
  real_tested_at?: string | null;
};

export async function createExportBatch(input: CreateExportInput) {
  const options = createExportSchema.parse(input);
  if (options.requiresPassphrase && options.passphrase.trim().length < 4) {
    throw new Error("passphrase required");
  }
  const nodes = selectNodes(options);
  if (!nodes.length) {
    throw new Error("no eligible nodes for export");
  }

  const now = new Date().toISOString();
  const batchCode = `B${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${nanoid(6).toUpperCase()}`;
  const publicSlug = nanoid(16);
  const batchDir = path.join(config.EXPORT_DIR, batchCode);
  fs.mkdirSync(batchDir, { recursive: true });

  const textFile = path.join(batchDir, "nodes.txt");
  const clashFile = path.join(batchDir, "clash.yaml");
  const singboxFile = path.join(batchDir, "sing-box.json");
  const readmeFile = path.join(batchDir, "README.txt");
  const guideFile = path.join(batchDir, "v2rayN-guide.txt");
  const usageFile = path.join(batchDir, "usage.txt");
  const disclaimerFile = path.join(batchDir, "disclaimer.txt");
  const feedbackFile = path.join(batchDir, "feedback-template.txt");
  const packageFile = path.join(batchDir, `${batchCode}.zip`);

  fs.writeFileSync(textFile, nodes.map((node) => node.content).join("\n") + "\n", "utf8");
  fs.writeFileSync(clashFile, clashTemplate(options, nodes), "utf8");
  fs.writeFileSync(singboxFile, singboxTemplate(options, nodes), "utf8");
  fs.writeFileSync(readmeFile, readmeTemplate(options, nodes), "utf8");
  fs.writeFileSync(guideFile, v2rayNGuide(), "utf8");
  fs.writeFileSync(usageFile, usageGuide(options, nodes), "utf8");
  fs.writeFileSync(disclaimerFile, disclaimer(), "utf8");
  fs.writeFileSync(feedbackFile, feedbackTemplate(batchCode), "utf8");

  await createPlainZip(batchDir, packageFile, [
    path.basename(textFile),
    path.basename(clashFile),
    path.basename(singboxFile),
    path.basename(readmeFile),
    path.basename(guideFile),
    path.basename(usageFile),
    path.basename(disclaimerFile),
    path.basename(feedbackFile)
  ]);

  const passphraseHash = options.requiresPassphrase ? await bcrypt.hash(options.passphrase, 12) : null;
  const status = "draft";
  const publishedAt = null;

  const transaction = db.transaction(() => {
    const batch = db
      .prepare(
        `INSERT INTO export_batches (
          batch_code, name, description, status, passphrase_hash, node_count,
          text_file_path, clash_file_path, singbox_file_path, readme_file_path,
          package_path, public_slug, export_options_json, quality_tier,
          requires_passphrase, allow_public_claim, allow_automation, allow_direct_download,
          allow_hermes_file, allow_hermes_link, last_tested_at, test_method, pass_rate,
          published_at, expires_at, max_downloads, ip_download_limit, wrong_passphrase_limit, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        batchCode,
        options.name,
        options.description,
        status,
        passphraseHash,
        nodes.length,
        textFile,
        clashFile,
        singboxFile,
        readmeFile,
        packageFile,
        publicSlug,
        JSON.stringify(redactExportOptions(options)),
        options.qualityTier ?? inferBatchQuality(nodes),
        options.requiresPassphrase ? 1 : 0,
        options.allowPublicClaim ? 1 : 0,
        options.allowAutomation ? 1 : 0,
        options.allowDirectDownload ? 1 : 0,
        options.allowHermesFile ? 1 : 0,
        options.allowHermesLink ? 1 : 0,
        latestTestTime(nodes),
        options.realOnly ? "xray-core" : "tcp",
        100,
        publishedAt,
        options.expiresAt ?? null,
        options.maxDownloads ?? null,
        options.ipDownloadLimit,
        options.wrongPassphraseLimit,
        now,
        now
      );
    const batchId = Number(batch.lastInsertRowid);

    db.prepare("INSERT INTO batch_stats (batch_id, updated_at) VALUES (?, ?)").run(batchId, now);
    const linkNode = db.prepare("INSERT INTO export_batch_nodes (batch_id, node_id, created_at) VALUES (?, ?, ?)");
    for (const node of nodes) {
      linkNode.run(batchId, node.id, now);
    }

    return batchId;
  });

  const batchId = transaction();

  return {
    id: batchId,
    batchCode,
    name: options.name,
    status,
    nodeCount: nodes.length,
    publicSlug,
    packagePath: packageFile,
    textFilePath: textFile,
    qualityTier: options.qualityTier ?? inferBatchQuality(nodes)
  };
}

export function listExportBatches() {
  return db
    .prepare(
      `SELECT id, batch_code, name, description, status, node_count, public_slug,
              quality_tier, requires_passphrase, allow_public_claim, allow_automation,
              allow_direct_download, allow_hermes_file, allow_hermes_link,
              last_tested_at, test_method, pass_rate,
              published_at, expires_at, max_downloads, ip_download_limit, wrong_passphrase_limit,
              created_at, updated_at
       FROM export_batches
       ORDER BY id DESC
       LIMIT 100`
    )
    .all();
}

export function publishExportBatch(batchId: number) {
  const now = new Date().toISOString();
  const batch = db.prepare("SELECT id, status FROM export_batches WHERE id = ?").get(batchId) as { id: number; status: string } | undefined;
  if (!batch) throw new Error("batch not found");
  if (batch.status === "closed" || batch.status === "expired") throw new Error("batch cannot be published");

  db.transaction(() => {
    db.prepare("UPDATE export_batches SET status = 'replaced', updated_at = ? WHERE status = 'published' AND id != ?").run(now, batchId);
    db.prepare("UPDATE export_batches SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?").run(now, now, batchId);
    db.prepare(
      `UPDATE nodes
       SET status = 'exported', exported_at = ?, export_batch_id = ?, updated_at = ?
       WHERE id IN (SELECT node_id FROM export_batch_nodes WHERE batch_id = ?)`
    ).run(now, batchId, now, batchId);
  })();
}

export function closeExportBatch(batchId: number) {
  const now = new Date().toISOString();
  const result = db.prepare("UPDATE export_batches SET status = 'closed', updated_at = ? WHERE id = ? AND status IN ('draft', 'published')").run(now, batchId);
  if (!result.changes) throw new Error("batch cannot be closed");
}

export function preflightExportBatch(batchId: number) {
  const rows = db
    .prepare(
      `SELECT nodes.id, nodes.status, nodes.latency_ms, nodes.real_latency_ms,
              nodes.real_status, nodes.last_tested_at, nodes.real_tested_at
       FROM export_batch_nodes
       JOIN nodes ON nodes.id = export_batch_nodes.node_id
       WHERE export_batch_nodes.batch_id = ?`
    )
    .all(batchId) as Array<{
      id: number;
      status: string;
      latency_ms: number | null;
      real_latency_ms: number | null;
      real_status: string | null;
      last_tested_at: string | null;
      real_tested_at: string | null;
    }>;
  if (!rows.length) throw new Error("batch has no nodes");

  const realChecked = rows.filter((row) => Boolean(row.real_status)).length;
  const realPassed = rows.filter((row) => row.real_status === "real_passed").length;
  const tcpPassed = rows.filter((row) => row.status === "test_passed" || row.status === "exported").length;
  const passBase = realChecked > 0 ? realChecked : rows.length;
  const passCount = realChecked > 0 ? realPassed : tcpPassed;
  const passRate = Math.round((passCount / passBase) * 100);
  const latencyValues = rows
    .map((row) => row.real_latency_ms ?? row.latency_ms)
    .filter((value): value is number => typeof value === "number");
  const avgLatency = latencyValues.length ? Math.round(latencyValues.reduce((sum, value) => sum + value, 0) / latencyValues.length) : null;
  const qualityTier = avgLatency === null ? null : qualityTierForLatency(avgLatency);
  const latestTestedAt = rows
    .map((row) => row.real_tested_at ?? row.last_tested_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? null;
  const testMethod = realChecked > 0 ? "xray-core" : "tcp";
  const riskLevel = passRate >= 90 ? "low" : passRate >= 70 ? "medium" : "high";

  db.prepare(
    `UPDATE export_batches
     SET pass_rate = ?, last_tested_at = ?, test_method = ?, quality_tier = COALESCE(?, quality_tier), updated_at = ?
     WHERE id = ?`
  ).run(passRate, latestTestedAt, testMethod, qualityTier, new Date().toISOString(), batchId);

  return {
    batchId,
    nodeCount: rows.length,
    checkedBy: testMethod,
    realChecked,
    realPassed,
    tcpPassed,
    passRate,
    avgLatency,
    qualityTier,
    latestTestedAt,
    riskLevel,
    message:
      riskLevel === "low"
        ? "发布风险较低，但免费节点仍可能随时失效。"
        : riskLevel === "medium"
          ? "建议发布前手动抽测，部分节点可能已经失效。"
          : "风险较高，建议重新测试或重新生成节点包。"
  };
}

export function deleteDraftBatch(batchId: number) {
  const batch = db
    .prepare("SELECT id, status, package_path, text_file_path FROM export_batches WHERE id = ?")
    .get(batchId) as { id: number; status: string; package_path?: string; text_file_path?: string } | undefined;
  if (!batch) throw new Error("batch not found");
  if (batch.status !== "draft") throw new Error("only draft batch can be deleted");
  db.transaction(() => {
    db.prepare("DELETE FROM export_batches WHERE id = ?").run(batchId);
  })();
}

function selectNodes(options: CreateExportInput) {
  const where = ["status = 'test_passed'"];
  const params: unknown[] = [];

  if (!options.includeExported) {
    where.push("exported_at IS NULL");
  }
  if (options.maxLatencyMs !== undefined) {
    where.push("COALESCE(real_latency_ms, latency_ms) <= ?");
    params.push(options.maxLatencyMs);
  }
  if (options.minLatencyMs !== undefined) {
    where.push("COALESCE(real_latency_ms, latency_ms) >= ?");
    params.push(options.minLatencyMs);
  }
  if (options.protocol) {
    where.push("protocol = ?");
    params.push(options.protocol);
  }
  if (options.qualityTier) {
    where.push("quality_tier = ?");
    params.push(options.qualityTier);
  }
  if (options.realOnly) {
    where.push("real_status = 'real_passed'");
  }

  const orderBy =
    options.sort === "latency_desc"
      ? "latency_ms DESC"
      : options.sort === "collected_desc"
        ? "collected_at DESC"
        : "latency_ms ASC";

  return db
    .prepare(
      `SELECT id, content, protocol, latency_ms, real_latency_ms, last_tested_at, real_tested_at
       FROM nodes
       WHERE ${where.join(" AND ")}
       ORDER BY CASE WHEN COALESCE(real_latency_ms, latency_ms) IS NULL THEN 1 ELSE 0 END, ${orderBy.replaceAll("latency_ms", "COALESCE(real_latency_ms, latency_ms)")}, collected_at DESC
       LIMIT ?`
    )
    .all(...params, options.count) as ExportNode[];
}

async function createPlainZip(cwd: string, packageFile: string, fileNames: string[]) {
  try {
    const args = ["-j", packageFile, ...fileNames.map((file) => path.join(cwd, file))];
    await execFileAsync("zip", args, {
      cwd,
      windowsHide: true
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "zip command failed";
    throw new Error(`failed to create zip: ${message}`);
  }
}

function clashTemplate(options: CreateExportInput, nodes: ExportNode[]) {
  return [
    "# Clash 配置模板",
    "# 第一版仍以 nodes.txt 为主导入文件；复杂协议参数后续会继续完善自动转换。",
    "# 本文件不包含后台来源、测试日志或服务器路径。",
    `# 批次名称：${options.name}`,
    `# 节点数量：${nodes.length}`,
    "mixed-port: 7890",
    "allow-lan: false",
    "mode: rule",
    "log-level: warning",
    "proxies: []",
    "proxy-groups:",
    "  - name: Auto",
    "    type: select",
    "    proxies:",
    "      - DIRECT",
    "rules:",
    "  - MATCH,Auto"
  ].join("\n");
}

function singboxTemplate(options: CreateExportInput, nodes: ExportNode[]) {
  return JSON.stringify(
    {
      log: { level: "warn" },
      notes: [
        "第一版仍以 nodes.txt 为主导入文件；复杂协议参数后续会继续完善自动转换。",
        "本文件不包含后台来源、测试日志或服务器路径。"
      ],
      package: {
        name: options.name,
        nodeCount: nodes.length
      },
      inbounds: [],
      outbounds: [{ type: "direct", tag: "direct" }],
      route: { final: "direct" }
    },
    null,
    2
  );
}

function readmeTemplate(options: CreateExportInput, nodes: ExportNode[]) {
  return [
    "README",
    "",
    `节点包名称：${options.name}`,
    `节点数量：${nodes.length}`,
    `质量档位：${qualityTierLabel(options.qualityTier ?? inferBatchQuality(nodes))}`,
    "推荐客户端：v2rayN / Clash Verge / Shadowrocket / sing-box",
    "",
    "重要说明：",
    "1. nodes.txt 是主格式，一行一个纯节点，可复制或导入客户端。",
    "2. clash.yaml 和 sing-box.json 是第一版兼容模板，复杂协议自动转换后续继续完善。",
    "3. 领取页已完成口令验证，ZIP 文件本身不再加密，下载后可直接打开。",
    "4. 免费节点存在时效性，部分节点失效属于正常情况。",
    "5. 本系统不承诺 100% 可用、长期可用或所有地区都可用。",
    "6. 本包不包含后台来源、服务器路径、Token、日志或数据库信息。"
  ].join("\n");
}

function inferBatchQuality(nodes: ExportNode[]) {
  const values = nodes.map((node) => node.real_latency_ms ?? node.latency_ms).filter((value): value is number => typeof value === "number");
  const avg = values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : 999;
  if (avg <= 100) return "high";
  if (avg <= 200) return "premium";
  if (avg <= 300) return "community";
  return "backup";
}

function qualityTierForLatency(latencyMs: number) {
  if (latencyMs <= 100) return "high";
  if (latencyMs <= 200) return "premium";
  if (latencyMs <= 300) return "community";
  return "backup";
}

function qualityTierLabel(value?: string | null) {
  const labels: Record<string, string> = {
    high: "高质量节点包（0-100ms）",
    premium: "普通优质节点包（100-200ms）",
    community: "社群福利节点包（200-300ms）",
    backup: "备用节点包（300ms 以上）"
  };
  return value ? labels[value] ?? value : "未分档";
}

function latestTestTime(nodes: ExportNode[]) {
  const times = nodes
    .map((node) => node.real_tested_at ?? node.last_tested_at)
    .filter((value): value is string => Boolean(value))
    .sort();
  return times.at(-1) ?? null;
}

function redactExportOptions(options: CreateExportInput) {
  const { passphrase: _passphrase, ...safeOptions } = options;
  return safeOptions;
}

function v2rayNGuide() {
  return [
    "v2rayN 导入说明",
    "",
    "1. 解压本节点包。",
    "2. 打开 v2rayN。",
    "3. 使用剪贴板导入或文件导入方式导入 nodes.txt。",
    "4. nodes.txt 中的内容是一行一个纯节点，不包含后台来源、延迟、备注或日志。",
    "5. ZIP 文件不加密，领取口令只用于领取页验证。",
    "6. 本批节点只经过后台基础初筛，不代表最终客户端真实使用延迟。"
  ].join("\n");
}

function usageGuide(options: CreateExportInput, nodes: ExportNode[]) {
  const latencies = nodes.map((node) => node.latency_ms).filter((value): value is number => typeof value === "number");
  return [
    "使用说明",
    "",
    `批次名称：${options.name}`,
    `导出数量：${nodes.length}`,
    `后台初筛最低延迟：${latencies.length ? `${Math.min(...latencies)}ms` : "无"}`,
    `后台初筛最高延迟：${latencies.length ? `${Math.max(...latencies)}ms` : "无"}`,
    "",
    "说明：后台初筛延迟只用于剔除明显不可连接节点，不等于真实客户端使用延迟。",
    "建议：先导入少量节点手动测试，确认可用后再继续使用。",
    "文件说明：nodes.txt 是纯节点文件，可以直接复制或导入客户端。",
    "兼容说明：ZIP 文件不加密，根目录直接放置 nodes.txt、clash.yaml、sing-box.json 等文件，方便 Windows、手机和 Telegram 打开。"
  ].join("\n");
}

function disclaimer() {
  return [
    "免责声明",
    "",
    "本节点包仅整理公开网络内容并进行基础连通性初筛。",
    "请遵守所在地法律法规和相关服务条款。",
    "节点可用性会随时间变化，本系统不保证持续可用。",
    "本文件不包含后台来源、服务器路径、Token、日志或其他内部信息。"
  ].join("\n");
}

function feedbackTemplate(batchCode: string) {
  return [
    "反馈模板",
    "",
    `批次编号：${batchCode}`,
    "地区：",
    "运营商：",
    "设备：",
    "使用软件：",
    "是否可用：",
    "备注："
  ].join("\n");
}
