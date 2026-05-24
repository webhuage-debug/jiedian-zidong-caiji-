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
  sort: z.enum(["latency_asc", "latency_desc", "collected_desc"]).default("latency_asc"),
  includeExported: z.boolean().default(false),
  passphrase: z.string().min(4).max(128),
  expiresAt: z.string().datetime().optional(),
  publish: z.boolean().default(false)
});

type CreateExportInput = z.infer<typeof createExportSchema>;

type ExportNode = {
  id: number;
  content: string;
  protocol: string;
  latency_ms: number | null;
};

export async function createExportBatch(input: CreateExportInput) {
  const options = createExportSchema.parse(input);
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
  const guideFile = path.join(batchDir, "v2rayN-guide.txt");
  const usageFile = path.join(batchDir, "usage.txt");
  const disclaimerFile = path.join(batchDir, "disclaimer.txt");
  const feedbackFile = path.join(batchDir, "feedback-template.txt");
  const packageFile = path.join(batchDir, `${batchCode}.zip`);

  fs.writeFileSync(textFile, nodes.map((node) => node.content).join("\n") + "\n", "utf8");
  fs.writeFileSync(guideFile, v2rayNGuide(), "utf8");
  fs.writeFileSync(usageFile, usageGuide(options, nodes), "utf8");
  fs.writeFileSync(disclaimerFile, disclaimer(), "utf8");
  fs.writeFileSync(feedbackFile, feedbackTemplate(batchCode), "utf8");

  await createPasswordZip(batchDir, packageFile, options.passphrase, [
    path.basename(textFile),
    path.basename(guideFile),
    path.basename(usageFile),
    path.basename(disclaimerFile),
    path.basename(feedbackFile)
  ]);

  const passphraseHash = await bcrypt.hash(options.passphrase, 12);
  const status = options.publish ? "published" : "draft";
  const publishedAt = options.publish ? now : null;

  const transaction = db.transaction(() => {
    const batch = db
      .prepare(
        `INSERT INTO export_batches (
          batch_code, name, description, status, passphrase_hash, node_count,
          text_file_path, package_path, public_slug, export_options_json,
          published_at, expires_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        batchCode,
        options.name,
        options.description,
        status,
        passphraseHash,
        nodes.length,
        textFile,
        packageFile,
        publicSlug,
        JSON.stringify(redactExportOptions(options)),
        publishedAt,
        options.expiresAt ?? null,
        now,
        now
      );
    const batchId = Number(batch.lastInsertRowid);

    db.prepare("INSERT INTO batch_stats (batch_id, updated_at) VALUES (?, ?)").run(batchId, now);
    const markNode = db.prepare("UPDATE nodes SET status = 'exported', exported_at = ?, export_batch_id = ?, updated_at = ? WHERE id = ?");
    for (const node of nodes) {
      markNode.run(now, batchId, now, node.id);
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
    textFilePath: textFile
  };
}

export function listExportBatches() {
  return db
    .prepare(
      `SELECT id, batch_code, name, description, status, node_count, public_slug,
              published_at, expires_at, created_at, updated_at
       FROM export_batches
       ORDER BY id DESC
       LIMIT 100`
    )
    .all();
}

function selectNodes(options: CreateExportInput) {
  const where = ["status = 'test_passed'"];
  const params: unknown[] = [];

  if (!options.includeExported) {
    where.push("exported_at IS NULL");
  }
  if (options.minLatencyMs !== undefined) {
    where.push("latency_ms >= ?");
    params.push(options.minLatencyMs);
  }
  if (options.maxLatencyMs !== undefined) {
    where.push("latency_ms <= ?");
    params.push(options.maxLatencyMs);
  }

  const orderBy =
    options.sort === "latency_desc"
      ? "latency_ms DESC"
      : options.sort === "collected_desc"
        ? "collected_at DESC"
        : "latency_ms ASC";

  return db
    .prepare(
      `SELECT id, content, protocol, latency_ms
       FROM nodes
       WHERE ${where.join(" AND ")}
       ORDER BY CASE WHEN latency_ms IS NULL THEN 1 ELSE 0 END, ${orderBy}, collected_at DESC
       LIMIT ?`
    )
    .all(...params, options.count) as ExportNode[];
}

async function createPasswordZip(cwd: string, packageFile: string, passphrase: string, fileNames: string[]) {
  try {
    await execFileAsync("zip", ["-j", "-P", passphrase, packageFile, ...fileNames.map((file) => path.join(cwd, file))], {
      cwd,
      windowsHide: true
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "zip command failed";
    throw new Error(`failed to create encrypted zip: ${message}`);
  }
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
    "5. 本批节点只经过后台基础初筛，不代表最终客户端真实使用延迟。"
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
    "文件说明：nodes.txt 是纯节点文件，可以直接复制或导入客户端。"
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
