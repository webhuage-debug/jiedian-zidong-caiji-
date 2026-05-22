import { config } from "../config.js";

export type DiscoveredSource = {
  url: string;
  sourceType: "github" | "web" | "text" | "subscription";
};

const githubRepoQueries = [
  "free v2ray nodes",
  "free proxy subscription",
  "vless trojan ss nodes",
  "vmess vless subscription"
];

const candidateFilePattern = /\.(txt|md|yaml|yml|json|list|conf)$/i;

export async function discoverPublicSources(signal: AbortSignal): Promise<DiscoveredSource[]> {
  const sources = new Map<string, DiscoveredSource>();

  for (const url of config.PUBLIC_SOURCE_SEEDS) {
    sources.set(url, { url, sourceType: inferSourceType(url) });
  }

  for (const query of githubRepoQueries) {
    for (const source of await discoverGitHubSources(query, signal)) {
      sources.set(source.url, source);
    }
  }

  return [...sources.values()].slice(0, 30);
}

async function discoverGitHubSources(query: string, signal: AbortSignal): Promise<DiscoveredSource[]> {
  const searchUrl = new URL("https://api.github.com/search/repositories");
  searchUrl.searchParams.set("q", query);
  searchUrl.searchParams.set("sort", "updated");
  searchUrl.searchParams.set("order", "desc");
  searchUrl.searchParams.set("per_page", "5");

  const response = await fetch(searchUrl, {
    signal,
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "public-node-admin/0.2.0"
    }
  });

  if (!response.ok) return [];
  const data = (await response.json()) as { items?: Array<{ full_name: string; default_branch?: string }> };
  const sources: DiscoveredSource[] = [];

  for (const repo of data.items ?? []) {
    sources.push(...(await discoverRepositoryFiles(repo.full_name, repo.default_branch ?? "main", signal)));
  }

  return sources;
}

async function discoverRepositoryFiles(repo: string, branch: string, signal: AbortSignal): Promise<DiscoveredSource[]> {
  const treeUrl = `https://api.github.com/repos/${repo}/git/trees/${encodeURIComponent(branch)}?recursive=1`;
  const response = await fetch(treeUrl, {
    signal,
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "public-node-admin/0.2.0"
    }
  });

  if (!response.ok) return [];
  const data = (await response.json()) as { tree?: Array<{ path: string; type: string; size?: number }> };

  return (data.tree ?? [])
    .filter((entry) => entry.type === "blob")
    .filter((entry) => candidateFilePattern.test(entry.path))
    .filter((entry) => (entry.size ?? 0) <= config.COLLECT_MAX_BYTES)
    .slice(0, 8)
    .map((entry) => ({
      url: `https://raw.githubusercontent.com/${repo}/${branch}/${entry.path}`,
      sourceType: "github" as const
    }));
}

function inferSourceType(url: string): DiscoveredSource["sourceType"] {
  if (url.includes("githubusercontent.com") || url.includes("github.com")) return "github";
  if (/\.(txt|list|conf)$/i.test(url)) return "text";
  if (/subscribe|subscription|sub/i.test(url)) return "subscription";
  return "web";
}
