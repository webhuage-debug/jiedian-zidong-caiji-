export type NodeEndpoint = {
  host: string;
  port: number;
};

export function parseNodeEndpoint(content: string, protocol: string): NodeEndpoint | null {
  try {
    if (protocol === "vmess") return parseVmess(content);
    if (protocol === "ssr") return parseSsr(content);
    if (protocol === "ss") return parseShadowsocks(content);
    return parseUrlLike(content);
  } catch {
    return null;
  }
}

function parseUrlLike(content: string): NodeEndpoint | null {
  const url = new URL(content);
  const port = Number(url.port);
  if (!url.hostname || !port) return null;
  return { host: stripBrackets(url.hostname), port };
}

function parseVmess(content: string): NodeEndpoint | null {
  const payload = content.replace(/^vmess:\/\//i, "");
  const json = JSON.parse(base64Decode(payload)) as { add?: string; port?: string | number };
  const port = Number(json.port);
  if (!json.add || !port) return null;
  return { host: json.add, port };
}

function parseSsr(content: string): NodeEndpoint | null {
  const payload = content.replace(/^ssr:\/\//i, "");
  const decoded = base64Decode(payload).split("/")[0] ?? "";
  const parts = decoded.split(":");
  const host = parts[0];
  const port = Number(parts[1]);
  if (!host || !port) return null;
  return { host, port };
}

function parseShadowsocks(content: string): NodeEndpoint | null {
  const value = content.replace(/^ss:\/\//i, "");
  const withoutFragment = value.split("#")[0] ?? "";

  if (withoutFragment.includes("@")) {
    const url = new URL(`ss://${withoutFragment}`);
    const port = Number(url.port);
    if (!url.hostname || !port) return null;
    return { host: stripBrackets(url.hostname), port };
  }

  const decoded = base64Decode(withoutFragment);
  const endpoint = decoded.split("@").pop();
  if (!endpoint) return null;
  const lastColon = endpoint.lastIndexOf(":");
  if (lastColon <= 0) return null;
  const host = endpoint.slice(0, lastColon);
  const port = Number(endpoint.slice(lastColon + 1));
  if (!host || !port) return null;
  return { host: stripBrackets(host), port };
}

function base64Decode(value: string) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  return Buffer.from(padded, "base64").toString("utf8");
}

function stripBrackets(host: string) {
  return host.replace(/^\[/, "").replace(/\]$/, "");
}
