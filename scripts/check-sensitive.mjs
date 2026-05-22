import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = process.cwd();
const forbiddenNames = [/^\.env$/, /\.sqlite3?$/i, /\.db$/i, /\.log$/i, /\.zip$/i];
const forbiddenContent = [
  /ADMIN_PASSWORD=(?!change-this-password-before-deploy)/,
  /SESSION_SECRET=(?!replace-with-a-long-random-secret-at-least-32-chars)/,
  /ghp_[A-Za-z0-9_]{20,}/,
  /github_pat_[A-Za-z0-9_]{20,}/,
  /(?:vmess|vless|trojan|ss|ssr|hysteria2|hy2|tuic):\/\/[A-Za-z0-9+/_?=#%&.:@;-]{20,}/i
];

const files = execFileSync("git", ["ls-files", "--others", "--cached", "--exclude-standard"], { cwd: root, encoding: "utf8" })
  .split(/\r?\n/)
  .filter(Boolean);

const failures = [];

for (const file of files) {
  if (file === "scripts/check-sensitive.mjs") continue;
  const base = path.basename(file);
  if (forbiddenNames.some((pattern) => pattern.test(base))) {
    failures.push(`Forbidden file name: ${file}`);
    continue;
  }

  const absolute = path.join(root, file);
  if (!fs.existsSync(absolute) || fs.statSync(absolute).isDirectory()) continue;
  const text = fs.readFileSync(absolute, "utf8");
  for (const pattern of forbiddenContent) {
    if (pattern.test(text)) {
      failures.push(`Sensitive-looking content in: ${file}`);
      break;
    }
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log(`Sensitive file check passed for ${files.length} tracked or pending files.`);
