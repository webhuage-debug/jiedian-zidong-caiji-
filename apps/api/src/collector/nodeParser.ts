import crypto from "node:crypto";

export const supportedProtocols = ["vmess", "vless", "trojan", "ss", "ssr", "hysteria2", "hy2", "tuic"] as const;
export type SupportedProtocol = (typeof supportedProtocols)[number];

export type ExtractedNode = {
  content: string;
  protocol: SupportedProtocol;
  hash: string;
};

const nodePattern = /\b(vmess|vless|trojan|ss|ssr|hysteria2|hy2|tuic):\/\/[^\s"'<>\\]+/gi;

export function extractNodes(input: string): ExtractedNode[] {
  const normalized = decodeHtmlEntities(input);
  const matches = normalized.matchAll(nodePattern);
  const seen = new Set<string>();
  const nodes: ExtractedNode[] = [];

  for (const match of matches) {
    const content = cleanNode(match[0]);
    const protocol = match[1].toLowerCase() as SupportedProtocol;
    if (!content || seen.has(content)) continue;
    seen.add(content);
    nodes.push({
      content,
      protocol,
      hash: sha256(content)
    });
  }

  return nodes;
}

export function sha256(value: string) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function cleanNode(value: string) {
  return value
    .trim()
    .replace(/[),.;\]}]+$/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&#38;/g, "&");
}

function decodeHtmlEntities(value: string) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}
