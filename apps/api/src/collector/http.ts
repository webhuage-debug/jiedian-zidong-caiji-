import { config } from "../config.js";

export async function fetchTextWithLimit(url: string, signal: AbortSignal) {
  const response = await fetch(url, {
    signal,
    headers: {
      "User-Agent": "public-node-admin/0.2.0",
      Accept: "text/plain,text/html,application/json,application/yaml,*/*;q=0.8"
    }
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) return "";

  const chunks: Uint8Array[] = [];
  let received = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    received += value.length;
    if (received > config.COLLECT_MAX_BYTES) {
      throw new Error("source too large");
    }
    chunks.push(value);
  }

  return Buffer.concat(chunks).toString("utf8");
}

export function withTimeout() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.HTTP_TIMEOUT_MS);
  return {
    signal: controller.signal,
    done: () => clearTimeout(timeout)
  };
}
