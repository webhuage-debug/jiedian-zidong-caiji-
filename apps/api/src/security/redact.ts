const nodeUrlPattern = /\b(vmess|vless|trojan|ss|ssr|hysteria2|hy2|tuic):\/\/[^\s"'<>\\]+/gi;
const uuidPattern = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi;
const tokenPattern = /\b(ghp|github_pat|sk|xoxb|xoxp)_[A-Za-z0-9_=-]{12,}\b/g;
const ipv4Pattern = /\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/g;

export function redactSensitiveText(value: unknown) {
  if (value === null || value === undefined) return value;
  return String(value)
    .replace(nodeUrlPattern, "[node-url-hidden]")
    .replace(uuidPattern, "[uuid-hidden]")
    .replace(tokenPattern, "[token-hidden]")
    .replace(ipv4Pattern, (match) => maskIp(match));
}

export function maskUrl(value: unknown) {
  if (!value) return value;
  try {
    const parsed = new URL(String(value));
    return `${parsed.protocol}//${parsed.hostname}/...`;
  } catch {
    return "[url-hidden]";
  }
}

export function maskIp(value: string) {
  const parts = value.split(".");
  if (parts.length !== 4) return "[ip-hidden]";
  return `${parts[0]}.${parts[1]}.*.*`;
}

export function maskMaybe(value: unknown, enabled: boolean) {
  return enabled ? redactSensitiveText(value) : value;
}
