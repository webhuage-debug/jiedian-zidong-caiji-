#!/usr/bin/env python3
"""Collect proxy node URIs and subscription-like links into SQLite."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import random
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from node_database import NodeDatabase
from node_region import is_collection_candidate

try:
    import yaml
except ImportError:
    yaml = None

DEFAULT_REPOS = [
    "free-nodes/clashfree",
    "MustafaBaqer/VestraNet-Nodes",
    "barry-far/V2ray-Config",
    "MatinGhanbari/v2ray-configs",
    "Epodonios/v2ray-configs",
    "ebrasha/free-v2ray-public-list",
    "mahdibland/V2RayAggregator",
    "ShatakVPN/ConfigForge-V2Ray",
    "V2RayRoot/V2RayConfig",
    "free-nodes/v2rayfree",
    "zengfr/free-vpn-subscribe",
    "FreeFolksOn/abc-configs-free-vpn-proxy-list",
    "mehdirzfx/v2ray-sub",
    "NiREvil/vless",
    "mermeroo/V2RAY-CLASH-BASE64-Subscription.Links",
    "Surfboardv2ray/v2ray-worker-sub",
]

NODE_SCHEMES = (
    "vless",
    "vmess",
    "ss",
    "ssr",
    "trojan",
    "hysteria",
    "hysteria2",
    "hy2",
    "tuic",
    "wireguard",
    "wg",
    "mieru",
    "juicity",
    "naive+https",
    "socks",
    "socks5",
)
SCHEME_PATTERN = "|".join(re.escape(item) for item in sorted(NODE_SCHEMES, key=len, reverse=True))
NODE_RE = re.compile(r"(?i)(?<![A-Za-z0-9+.-])(" + SCHEME_PATTERN + r")://[^\s\"'<>`\]\[{}|]+")
URL_RE = re.compile(r"(?i)https?://[^\s\"'<>`\]\[{}|]+")
BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/=_-])")

TEXT_SUFFIXES = {
    ".txt", ".yaml", ".yml", ".json", ".conf", ".config", ".list", ".csv",
    ".md", ".ini", ".toml", ".sub", ".base64", ".b64", ".jsonl",
}
LIKELY_NAMES = (
    "sub", "subscription", "node", "nodes", "proxy", "config", "clash", "sing", "singbox",
    "xray", "v2ray", "base64", "vless", "vmess", "ss", "shadowsocks", "trojan", "hy2",
    "hysteria", "tuic", "wireguard", "protocol",
)
HIGH_VALUE_PATHS = (
    "sub", "subs", "subscriptions", "subscription", "protocols", "protocol", "base64", "raw",
    "clash", "singbox", "sing-box", "surge", "proxy", "proxies",
    "v2ray", "xray", "vless", "vmess", "shadowsocks", "trojan", "ssr", "hy2",
    "hysteria", "tuic", "wireguard",
)
LOW_VALUE_PATHS = (
    "/.github/", "/.git/", "/node_modules/", "/vendor/", "/dist/", "/build/",
    "/docs/", "/doc/", "/website/", "/site/", "/test/", "/tests/", "/script/", "/scripts/",
    "/assets/", "/asset/", "/images/", "/image/", "/icons/", "/icon/", "/textures/", "/texture/",
    "/css/", "/js/", "/pages/", "/public/assets/", "/src/settings/", "/src/contents/", "/src/utils/",
)
LOW_VALUE_FILES = ("license", "changelog", "contributing", "code_of_conduct", ".lock")
DEFAULT_MAX_TREE_DEPTH = 3
README_NODE_HINTS = ("vmess://", "vless://", "trojan://", "ss://", "ssr://")
TRAILING_PUNCTUATION = ".,;:!?)]}"
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}
LOG_LEVELS = {"compact": 0, "detail": 1, "nodes": 2}


def readable_error(error: object) -> str:
    text = str(error)
    if "curl: (28)" in text and "Operation timed out" in text:
        return "请求超时：在超时时间内没有收到数据"
    if "curl: (28)" in text and "Connection timed out" in text:
        return "连接超时：无法在超时时间内连接目标站点"
    if "Operation timed out" in text:
        return "请求超时"
    if "Connection timed out" in text:
        return "连接超时"
    if "Failed to perform" in text:
        return "请求执行失败"
    return text


@dataclass(frozen=True)
class Finding:
    kind: str
    value: str
    repo: str
    source: str
    encoding: str
    score: int = 0


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


class CollectorLogger:
    def __init__(self, level: str = "detail"):
        self.level = LOG_LEVELS[level]
        self.lock = threading.Lock()
        self.started_at = time.monotonic()
        self.counters: Dict[str, int] = {
            "repositories": 0,
            "directory_pages": 0,
            "candidate_files": 0,
            "fetched_files": 0,
            "skipped_dirs": 0,
            "parsed_nodes": 0,
            "inserted_nodes": 0,
            "duplicate_nodes": 0,
            "region_rejected": 0,
            "failed_requests": 0,
            "no_node_files": 0,
        }

    def emit(self, message: str, verbosity: int = 0, **fields) -> None:
        for key in list(self.counters):
            delta = fields.get(key + "_delta")
            if delta:
                self.counters[key] += int(delta)
        payload = {"message": message, "visible": self.level >= verbosity, **fields}
        with self.lock:
            print("@event " + json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)

    def emit_summary(self, failed_sources: int) -> None:
        elapsed = time.monotonic() - self.started_at
        self.emit(
            "[采集汇总] repos={repositories} dirs={directory_pages} raw_files={fetched_files} "
            "skipped_dirs={skipped_dirs} candidate_files={candidate_files} parsed={parsed_nodes} "
            "inserted={inserted_nodes} duplicates={duplicate_nodes} region_rejected={region_rejected} "
            "failed_sources={failed_sources} elapsed={elapsed:.1f}s".format(
                failed_sources=failed_sources,
                elapsed=elapsed,
                **self.counters,
            ),
            0,
            collection_summary=True,
            elapsed_seconds=round(elapsed, 1),
        )


class ScraplingClient:
    def __init__(
        self,
        timeout: int = 20,
        delay: float = 1.0,
        delay_jitter: float = 0.5,
        logger: Optional[CollectorLogger] = None,
    ):
        self.timeout = timeout
        self.delay = delay
        self.delay_jitter = delay_jitter
        self.logger = logger or CollectorLogger()
        self.lock = threading.Lock()
        self.active_requests = 0
        try:
            from scrapling.fetchers import Fetcher
        except ImportError as exc:
            raise SystemExit("Scrapling Fetcher is required. Install it with: pip install -r requirements.txt") from exc
        self.fetcher = Fetcher

    def get_text(self, url: str, category: str = "网页") -> str:
        timeout = self.timeout
        if category == "目录页":
            timeout = min(timeout, 10)
        elif category == "Raw 文件":
            timeout = max(timeout, 25)
        elif category == "订阅":
            timeout = max(timeout, 20)
        wait = self.delay + random.uniform(0, self.delay_jitter)
        if wait:
            time.sleep(wait)
        started = time.monotonic()
        with self.lock:
            self.active_requests += 1
            active = self.active_requests
        self.logger.emit("[请求] " + category + " | " + url, 1, current_url=url, active_requests=active)
        try:
            page = self.fetcher.get(url, timeout=timeout, retries=2)
            elapsed = time.monotonic() - started
            self.logger.emit(
                "[成功] " + category + " | " + str(page.status) + " | " + f"{elapsed:.2f}s | " + url,
                1,
                current_url=url,
            )
            return page.body.decode("utf-8", errors="replace")
        except Exception as exc:
            self.logger.emit(
                "[失败] " + category + " | " + readable_error(exc) + " | " + url,
                0,
                current_url=url,
                failed_requests_delta=1,
            )
            raise
        finally:
            with self.lock:
                self.active_requests -= 1
                active = self.active_requests
            self.logger.emit("[请求完成] 活动请求 " + str(active), 1, active_requests=active)


class DatabaseNodeSink:
    def __init__(self, database_path: Path, logger: Optional[CollectorLogger] = None):
        self.database = NodeDatabase(database_path)
        self.logger = logger or CollectorLogger()

    def consume(self, findings: Iterable[Finding]) -> None:
        parsed_nodes = [finding for finding in findings if finding.kind == "node"]
        kept_nodes = [
            finding for finding in parsed_nodes
            if is_collection_candidate({
                "uri": finding.value,
                "repo": finding.repo,
                "source": finding.source,
                "encoding": finding.encoding,
            })
        ]
        nodes = [(finding.value, finding.repo, finding.source, finding.encoding) for finding in kept_nodes]
        stats = self.database.upsert_nodes_with_stats(nodes)
        rejected = len(parsed_nodes) - len(kept_nodes)
        if not stats["parsed"] and not rejected:
            return
        self.logger.emit(
            "[入库] 解析 " + str(stats["parsed"]) + " | 新增 " + str(stats["inserted"])
            + " | 重复 " + str(stats["duplicates"]) + " | 前置过滤 " + str(rejected)
            + " | 节点库 " + str(stats["total"]),
            0,
            parsed_nodes_delta=len(parsed_nodes),
            inserted_nodes_delta=stats["inserted"],
            duplicate_nodes_delta=stats["duplicates"],
            region_rejected_delta=rejected,
            database_total=stats["total"],
        )
        inserted = set(stats["inserted_uris"])
        if self.logger.level >= LOG_LEVELS["nodes"]:
            seen: Set[str] = set()
            for uri, _, _, _ in nodes:
                status = "新增入库" if uri in inserted and uri not in seen else "重复过滤"
                self.logger.emit("[节点] " + status + " | " + safe_node_ref(uri), 2)
                seen.add(uri)

    def close(self) -> None:
        self.database.close()

    def source_profiles(self, repo: str) -> Dict[str, int]:
        return self.database.source_profiles(repo)

    def record_source_result(self, repo: str, source: str, nodes: int, success: bool) -> None:
        self.database.record_source_result(repo, source, nodes, success)


def trim_value(value: str) -> str:
    return value.rstrip(TRAILING_PUNCTUATION)


def safe_node_ref(node: str) -> str:
    parsed = urllib.parse.urlsplit(node)
    scheme = (parsed.scheme or node.split("://", 1)[0]).lower()
    digest = hashlib.sha256(node.encode("utf-8", errors="replace")).hexdigest()[:8]
    if parsed.hostname and parsed.port:
        return scheme + "://***@" + parsed.hostname + ":" + str(parsed.port) + "#hash_" + digest
    return scheme + "://***#hash_" + digest


def classify_url(url: str, context: str) -> Tuple[str, int]:
    lowered = (url + " " + context).lower()
    score = 0
    for hint in ("sub", "subscribe", "subscription", "clash", "sing-box", "singbox", "v2ray", "xray", "base64"):
        if hint in lowered:
            score += 2
    path = urllib.parse.urlsplit(url).path.lower()
    if any(path.endswith(suffix) for suffix in (".txt", ".yaml", ".yml", ".json", ".conf", ".b64", ".base64")):
        score += 1
    if "token=" in lowered or "target=" in lowered:
        score += 1
    return ("subscription_link" if score >= 2 else "link", score)


def decode_base64(candidate: str) -> Optional[str]:
    compact = "".join(candidate.split())
    if len(compact) < 32:
        return None
    padded = compact + "=" * (-len(compact) % 4)
    for altchars in (None, b"-_"):
        try:
            decoded = base64.b64decode(padded, altchars=altchars, validate=True)
            text = decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        printable = sum(char.isprintable() or char in "\r\n\t" for char in text)
        if text and printable / len(text) > 0.9:
            return text
    return None


def encoded(value) -> str:
    return urllib.parse.quote(str(value), safe="")


def first_present(*values):
    for value in values:
        if value not in (None, "", False):
            return value
    return None


def nested_get(value: dict, *path):
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def add_query(query: dict, key: str, value) -> None:
    if value not in (None, "", False):
        query[key] = value


def proxy_uri(proxy: dict) -> Optional[str]:
    kind = str(proxy.get("type", "")).lower()
    scheme = {"shadowsocks": "ss", "hy2": "hysteria2"}.get(kind, kind)
    server = proxy.get("server") or proxy.get("address")
    port = proxy.get("port") or proxy.get("server_port")
    name = encoded(proxy.get("name") or proxy.get("tag") or "")
    if not scheme or not server or not port:
        return None
    suffix = "#" + name if name else ""
    if scheme == "ss":
        method = proxy.get("cipher") or proxy.get("method")
        password = proxy.get("password")
        if not method or password is None:
            return None
        secret = base64.urlsafe_b64encode((str(method) + ":" + str(password)).encode()).decode().rstrip("=")
        return "ss://" + secret + "@" + str(server) + ":" + str(port) + suffix
    if scheme == "vmess":
        payload = {
            "v": "2",
            "ps": proxy.get("name") or proxy.get("tag") or "",
            "add": server,
            "port": str(port),
            "id": proxy.get("uuid") or proxy.get("id") or "",
            "aid": str(proxy.get("alterId") or proxy.get("alter_id") or 0),
            "scy": proxy.get("cipher") or "auto",
            "net": proxy.get("network") or proxy.get("transport", {}).get("type") or "tcp",
            "type": "none",
            "host": proxy.get("servername") or proxy.get("sni") or "",
            "path": "",
            "tls": "tls" if proxy.get("tls") or proxy.get("security") == "tls" else "",
        }
        if not payload["id"]:
            return None
        return "vmess://" + base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode().rstrip("=")
    credential = proxy.get("uuid") or proxy.get("password") or proxy.get("token")
    if scheme == "tuic" and proxy.get("uuid") and proxy.get("password"):
        credential = str(proxy["uuid"]) + ":" + str(proxy["password"])
    if credential is None:
        return None
    query = {}
    transport = proxy.get("transport") if isinstance(proxy.get("transport"), dict) else {}
    network = first_present(proxy.get("network"), transport.get("type"))
    if not network:
        for flag, name in (("ws-opts", "ws"), ("grpc-opts", "grpc"), ("xhttp-opts", "xhttp")):
            if isinstance(proxy.get(flag), dict):
                network = name
                break
    add_query(query, "type", network)
    add_query(query, "flow", proxy.get("flow"))
    add_query(query, "sni", first_present(proxy.get("servername"), proxy.get("sni"), transport.get("serverName")))
    add_query(query, "security", proxy.get("security"))
    add_query(query, "alpn", proxy.get("alpn"))
    add_query(query, "fp", first_present(proxy.get("client-fingerprint"), proxy.get("client_fingerprint")))
    add_query(query, "allowInsecure", proxy.get("skip-cert-verify"))
    if proxy.get("tls") and "security" not in query:
        query["security"] = "tls"
    reality_opts = proxy.get("reality-opts") if isinstance(proxy.get("reality-opts"), dict) else {}
    add_query(query, "pbk", first_present(reality_opts.get("public-key"), reality_opts.get("public_key"), proxy.get("public-key"), proxy.get("public_key")))
    add_query(query, "sid", first_present(reality_opts.get("short-id"), reality_opts.get("short_id"), proxy.get("short-id"), proxy.get("short_id")))
    add_query(query, "spx", first_present(reality_opts.get("spider-x"), reality_opts.get("spider_x")))
    if "pbk" in query:
        query["security"] = "reality"
    ws_opts = proxy.get("ws-opts") if isinstance(proxy.get("ws-opts"), dict) else {}
    xhttp_opts = proxy.get("xhttp-opts") if isinstance(proxy.get("xhttp-opts"), dict) else {}
    headers = ws_opts.get("headers") if isinstance(ws_opts.get("headers"), dict) else {}
    add_query(query, "path", first_present(ws_opts.get("path"), xhttp_opts.get("path"), transport.get("path"), proxy.get("path")))
    add_query(query, "host", first_present(headers.get("Host"), headers.get("host"), ws_opts.get("host"), xhttp_opts.get("host"), transport.get("host"), proxy.get("host")))
    grpc_opts = proxy.get("grpc-opts") if isinstance(proxy.get("grpc-opts"), dict) else {}
    add_query(query, "serviceName", first_present(grpc_opts.get("grpc-service-name"), grpc_opts.get("serviceName"), nested_get(transport, "grpcSettings", "serviceName")))
    add_query(query, "mode", first_present(xhttp_opts.get("mode"), nested_get(transport, "xhttpSettings", "mode")))
    query_text = urllib.parse.urlencode(query, doseq=True)
    return (
        scheme + "://" + encoded(credential) + "@" + str(server) + ":" + str(port)
        + ("?" + query_text if query_text else "") + suffix
    )


def structured_nodes(text: str) -> List[str]:
    if yaml is None or len(text) > 4 * 1024 * 1024:
        return []
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    nodes: List[str] = []

    def visit(value) -> None:
        if isinstance(value, dict):
            if value.get("type") and (value.get("server") or value.get("address")):
                uri = proxy_uri(value)
                if uri:
                    nodes.append(uri)
            for key in ("proxies", "outbounds"):
                visit(value.get(key))
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(document)
    return nodes


def extract_findings(
    text: str,
    repo: str,
    source: str,
    encoding: str = "plain",
    depth: int = 0,
    seen_payloads: Optional[Set[str]] = None,
) -> List[Finding]:
    findings: List[Finding] = []
    seen_payloads = seen_payloads if seen_payloads is not None else set()

    for match in NODE_RE.finditer(text):
        findings.append(Finding("node", trim_value(match.group(0)), repo, source, encoding))

    for node in structured_nodes(text):
        findings.append(Finding("node", node, repo, source, encoding))

    for match in URL_RE.finditer(text):
        value = trim_value(match.group(0))
        kind, score = classify_url(value, text[max(0, match.start() - 80):match.end() + 80])
        findings.append(Finding(kind, value, repo, source, encoding, score))

    if depth >= 2:
        return findings

    candidates = [text.strip()] if len(text.strip()) >= 32 else []
    candidates.extend(match.group(0) for match in BASE64_RE.finditer(text))
    for candidate in candidates:
        decoded = decode_base64(candidate)
        if not decoded or decoded in seen_payloads or decoded == text:
            continue
        seen_payloads.add(decoded)
        findings.extend(extract_findings(decoded, repo, source, "base64", depth + 1, seen_payloads))
    return findings


def should_download(path: str, size: Optional[int], max_bytes: int) -> bool:
    lowered = "/" + path.lower()
    if size is not None and (size <= 0 or size > max_bytes):
        return False
    if is_low_value_path(path):
        return False
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    if any(name.startswith(item) or item in name for item in LOW_VALUE_FILES):
        return False
    return suffix in TEXT_SUFFIXES or any(hint in lowered for hint in LIKELY_NAMES)


def is_high_value_path(path: str) -> bool:
    lowered = path.lower()
    return any(hint in lowered for hint in HIGH_VALUE_PATHS)


def is_low_value_path(path: str) -> bool:
    normalized = "/" + path.strip("/").lower() + "/"
    if "/src/" in normalized and is_high_value_path(path):
        return False
    return any(part in normalized for part in LOW_VALUE_PATHS)


def should_parse_file_content(path: str, text: str) -> bool:
    if Path(path).name.lower().startswith("readme"):
        lowered = text.lower()
        return any(hint in lowered for hint in README_NODE_HINTS)
    return True


def should_follow_tree(repo: str, tree_url: str, max_depth: int, logger: CollectorLogger) -> bool:
    path = tree_path(repo, tree_url)
    if is_low_value_path(path):
        logger.emit("[跳过] 低价值目录 | " + tree_url, 1, skipped_dirs_delta=1)
        return False
    depth = tree_depth(repo, tree_url)
    if depth > max_depth:
        logger.emit("[跳过] 目录深度超过限制 " + str(max_depth) + " | " + tree_url, 1, skipped_dirs_delta=1)
        return False
    return True


def path_priority(path: str, profile_scores: Optional[Dict[str, int]] = None) -> Tuple[int, int, str]:
    lowered = path.lower()
    profile_score = (profile_scores or {}).get(path, 0)
    if any(hint in lowered for hint in HIGH_VALUE_PATHS):
        return (0, -profile_score, lowered)
    if Path(path).name.lower().startswith("readme"):
        return (3, -profile_score, lowered)
    if any(hint in lowered for hint in LIKELY_NAMES):
        return (1, -profile_score, lowered)
    return (2, -profile_score, lowered)


def deduplicate(findings: Iterable[Finding]) -> List[Finding]:
    best: Dict[Tuple[str, str], Finding] = {}
    for finding in findings:
        key = (finding.kind, finding.value)
        previous = best.get(key)
        if previous is None or finding.score > previous.score:
            best[key] = finding
    return sorted(best.values(), key=lambda item: (item.kind, item.value))


def is_safe_subscription_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in BLOCKED_HOSTS or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def resolve_subscriptions(
    client: ScraplingClient,
    findings: Sequence[Finding],
    max_subscriptions: int,
    max_depth: int,
    max_bytes: int,
    on_findings: Optional[Callable[[Iterable[Finding]], None]] = None,
    logger: Optional[CollectorLogger] = None,
    workers: int = 3,
) -> List[Finding]:
    logger = logger or CollectorLogger()
    resolved: List[Finding] = []
    queued: Set[str] = set()
    visited: Set[str] = set()
    queue: List[Tuple[str, str, int]] = []

    def add_links(items: Iterable[Finding], depth: int) -> None:
        for item in items:
            if item.kind != "subscription_link" or item.value in queued or item.value in visited:
                continue
            if not is_safe_subscription_url(item.value):
                logger.emit("[跳过] 不安全订阅地址 | " + item.value, 0)
                continue
            queued.add(item.value)
            queue.append((item.value, item.repo, depth))

    add_links(findings, 0)
    def fetch_subscription(url: str, repo: str, depth: int) -> Tuple[str, int, List[Finding]]:
        logger.emit("[订阅] 开始解析 | " + url, 0, current_url=url)
        try:
            text = client.get_text(url, "订阅")
            if len(text.encode("utf-8")) > max_bytes:
                logger.emit("[跳过] 订阅超过大小限制 | " + url, 0)
                return url, depth, []
            extracted = extract_findings(text, repo, url)
            nodes = sum(item.kind == "node" for item in extracted)
            logger.emit("[订阅] 完成 | 节点 " + str(nodes) + " | " + url, 0)
            return url, depth, extracted
        except Exception as exc:
            logger.emit("[失败] 订阅解析失败 | " + str(exc) + " | " + url, 0)
            return url, depth, []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while queue and len(visited) < max_subscriptions:
            batch: List[Tuple[str, str, int]] = []
            while queue and len(batch) < workers and len(visited) < max_subscriptions:
                url, repo, depth = queue.pop(0)
                queued.discard(url)
                if url in visited:
                    continue
                visited.add(url)
                batch.append((url, repo, depth))
            futures = [executor.submit(fetch_subscription, url, repo, depth) for url, repo, depth in batch]
            for future in as_completed(futures):
                _, depth, extracted = future.result()
                resolved.extend(extracted)
                if on_findings:
                    on_findings(extracted)
                if depth < max_depth:
                    add_links(extracted, depth + 1)
    if queue:
        logger.emit("[限制] 订阅抓取达到上限 " + str(max_subscriptions), 0)
    return resolved


def page_links(html: str, base_url: str) -> List[str]:
    parser = LinkParser()
    parser.feed(html)
    return [urllib.parse.urljoin(base_url, link) for link in parser.links]


def discover_blob_urls(
    client: ScraplingClient,
    repo: str,
    max_pages: int,
    max_depth: int = DEFAULT_MAX_TREE_DEPTH,
    logger: Optional[CollectorLogger] = None,
) -> List[Finding]:
    logger = logger or CollectorLogger()
    prefix = "https://github.com/" + repo
    queue = [prefix, prefix + "/tree/main", prefix + "/tree/master"]
    visited: Set[str] = set()
    findings_by_value: Dict[str, Finding] = {}

    def add_finding(finding: Finding) -> None:
        previous = findings_by_value.get(finding.value)
        if previous is None or finding.score > previous.score:
            findings_by_value[finding.value] = finding
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        logger.emit("[目录] 扫描 | " + url, 0, current_url=url, directory_pages_delta=1)
        try:
            html = client.get_text(url, "目录页")
        except Exception as exc:
            logger.emit("[失败] 目录页扫描失败，继续下一个目录 | " + readable_error(exc) + " | " + url, 0)
            continue
        for finding in extract_findings(html, repo, url):
            if finding.kind in ("link", "subscription_link"):
                normalized = normalize_discovered_url(repo, finding.value)
                if normalized:
                    kind, value, source, score = normalized
                    add_finding(Finding(kind, value, repo, source, "page-link", finding.score + score))
                elif finding.kind == "subscription_link" and is_safe_subscription_url(finding.value):
                    add_finding(finding)
        for link in page_links(html, url):
            clean = link.split("#", 1)[0].split("?", 1)[0]
            if clean.startswith(prefix + "/blob/"):
                path = blob_path(repo, clean)
                add_finding(Finding("file", raw_url_from_blob(repo, clean), repo, path, "github-page", path_score(path)))
            elif clean.startswith(prefix + "/tree/") and clean not in visited and clean not in queue:
                if should_follow_tree(repo, clean, max_depth, logger):
                    queue.append(clean)
    if queue:
        logger.emit("[限制] " + repo + " 目录页达到上限 " + str(max_pages), 0)
    return sorted(findings_by_value.values(), key=lambda item: (item.kind, item.source, item.value))


def normalize_discovered_url(repo: str, url: str) -> Optional[Tuple[str, str, str, int]]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return None
    hostname = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")
    github_blob_prefix = repo + "/blob/"
    raw_prefix = repo + "/"
    if hostname == "github.com" and path.startswith(github_blob_prefix):
        blob_url = "https://github.com/" + path
        source = blob_path(repo, blob_url)
        return ("file", raw_url_from_blob(repo, blob_url), source, path_score(source))
    if hostname == "raw.githubusercontent.com" and path.startswith(raw_prefix):
        parts = path.split("/", 3)
        if len(parts) == 4:
            source = parts[3]
            return ("file", url, source, path_score(source))
    if is_safe_subscription_url(url):
        kind, score = classify_url(url, "")
        if kind == "subscription_link":
            return (kind, url, url, score)
    return None


def blob_path(repo: str, blob_url: str) -> str:
    marker = "https://github.com/" + repo + "/blob/"
    remainder = blob_url[len(marker):]
    parts = remainder.split("/", 1)
    return parts[1] if len(parts) == 2 else remainder


def raw_url_from_blob(repo: str, blob_url: str) -> str:
    marker = "https://github.com/" + repo + "/blob/"
    remainder = blob_url[len(marker):]
    parts = remainder.split("/", 1)
    if len(parts) != 2:
        return blob_url.replace("/blob/", "/raw/", 1)
    branch, path = parts
    return "https://raw.githubusercontent.com/" + repo + "/" + branch + "/" + path


def path_score(path: str) -> int:
    lowered = path.lower()
    score = 0
    for hint in HIGH_VALUE_PATHS:
        if hint in lowered:
            score += 20
    for hint in LIKELY_NAMES:
        if hint in lowered:
            score += 5
    if Path(path).name.lower().startswith("readme"):
        score += 2
    return score


def tree_depth(repo: str, tree_url: str) -> int:
    path = tree_path(repo, tree_url)
    if not path:
        return 0
    return len([part for part in path.split("/") if part])


def tree_path(repo: str, tree_url: str) -> str:
    marker = "https://github.com/" + repo + "/tree/"
    if not tree_url.startswith(marker):
        return ""
    remainder = tree_url[len(marker):]
    parts = remainder.split("/", 1)
    if len(parts) == 1:
        return ""
    return parts[1]


def crawl_repo(
    client: ScraplingClient,
    repo: str,
    max_files: int,
    max_bytes: int,
    max_pages: int,
    max_depth: int = DEFAULT_MAX_TREE_DEPTH,
    workers: int = 5,
    on_findings: Optional[Callable[[Iterable[Finding]], None]] = None,
    logger: Optional[CollectorLogger] = None,
    source_profiles: Optional[Dict[str, int]] = None,
    on_source_result: Optional[Callable[[str, str, int, bool], None]] = None,
) -> List[Finding]:
    logger = logger or CollectorLogger()
    findings: List[Finding] = []
    discovered = discover_blob_urls(client, repo, max_pages, max_depth, logger)
    files = []
    link_findings: List[Finding] = []
    seen_paths: Set[str] = set()
    for item in discovered:
        if item.kind != "file":
            link_findings.append(item)
            continue
        path = item.source
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if should_download(path, None, max_bytes):
            files.append((path, item.value))
        else:
            logger.emit("[跳过] 低价值文件 | " + repo + "/" + path, 1)
    files.sort(key=lambda item: path_priority(item[0], source_profiles))
    if len(files) > max_files:
        logger.emit("[限制] " + repo + " 候选文件达到上限 " + str(max_files), 0)
    selected = files[:max_files]
    logger.emit(
        "[发现] " + repo + " | 候选文件 " + str(len(selected)),
        0,
        candidate_files_delta=len(selected),
    )

    def fetch_file(path: str, blob_url: str) -> Tuple[str, List[Finding], bool, int]:
        url = blob_url
        try:
            logger.emit("[文件] 开始 | " + repo + "/" + path, 0, current_url=url)
            text = client.get_text(url, "Raw 文件")
            if len(text.encode("utf-8")) > max_bytes:
                logger.emit("[跳过] 文件超过大小限制 | " + repo + "/" + path, 0)
                return path, [], False, 0
            if not should_parse_file_content(path, text):
                logger.emit("[跳过] README 未包含节点协议 | " + repo + "/" + path, 1, no_node_files_delta=1)
                return path, [], True, 0
            extracted = extract_findings(text, repo, path)
            nodes = sum(item.kind == "node" for item in extracted)
            logger.emit(
                "[文件] 完成 | " + repo + "/" + path + " | 节点 " + str(nodes),
                0,
                fetched_files_delta=1,
                no_node_files_delta=1 if nodes == 0 else 0,
            )
            return path, extracted, True, nodes
        except Exception as exc:
            logger.emit("[失败] 文件抓取失败 | " + repo + "/" + path + " | " + readable_error(exc), 0)
            return path, [], False, 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_file, path, blob_url) for path, blob_url in selected]
        for future in as_completed(futures):
            path, extracted, success, nodes = future.result()
            if on_source_result:
                on_source_result(repo, path, nodes, success)
            findings.extend(extracted)
            if on_findings:
                on_findings(extracted)
    if link_findings:
        findings.extend(link_findings)
        if on_findings:
            on_findings(link_findings)
    return findings


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", dest="repos", help="GitHub owner/repo; repeat to add repositories")
    parser.add_argument("--repo-file", type=Path, help="file containing one owner/repo per line")
    parser.add_argument("--shuffle-repos", action="store_true", help="shuffle repository order before crawling")
    parser.add_argument("--database", type=Path, default=Path("data/nodes.db"), help="SQLite database path")
    parser.add_argument("--max-files", type=int, default=400, help="maximum candidate files per repository")
    parser.add_argument("--max-pages", type=int, default=500, help="maximum GitHub directory pages per repository")
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_TREE_DEPTH, help="maximum GitHub directory depth to follow; capped at 3 by default")
    parser.add_argument("--max-bytes", type=int, default=4 * 1024 * 1024, help="maximum bytes per file")
    parser.add_argument("--max-subscriptions", type=int, default=500, help="maximum subscription URLs to resolve")
    parser.add_argument("--subscription-depth", type=int, default=2, help="maximum nested subscription link depth")
    parser.add_argument("--no-resolve-subscriptions", action="store_true", help="do not fetch discovered subscription URLs")
    parser.add_argument("--delay", type=float, default=1.0, help="minimum delay before each HTTP request")
    parser.add_argument("--delay-jitter", type=float, default=0.5, help="random extra delay before each HTTP request")
    parser.add_argument("--workers", type=int, default=5, help="concurrent raw file fetch workers")
    parser.add_argument("--log-level", choices=sorted(LOG_LEVELS), default="detail")
    return parser.parse_args(argv)


def load_repos(args: argparse.Namespace) -> List[str]:
    repos = list(args.repos or [])
    if args.repo_file:
        repos.extend(
            line.strip() for line in args.repo_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    repos = repos or list(DEFAULT_REPOS)
    if args.shuffle_repos:
        random.shuffle(repos)
    return repos


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.max_files <= 0 or args.max_pages <= 0 or args.max_bytes <= 0 or args.max_subscriptions <= 0 or args.workers <= 0:
        raise SystemExit("--max-files, --max-pages, --max-bytes, --max-subscriptions and --workers must be positive")
    if args.subscription_depth < 0 or args.delay < 0 or args.delay_jitter < 0 or args.max_depth < 0:
        raise SystemExit("--subscription-depth, --delay, --delay-jitter and --max-depth must not be negative")
    logger = CollectorLogger(args.log_level)
    client = ScraplingClient(delay=args.delay, delay_jitter=args.delay_jitter, logger=logger)
    sink = DatabaseNodeSink(args.database, logger)
    all_findings: List[Finding] = []
    failed = 0
    effective_depth = min(args.max_depth, DEFAULT_MAX_TREE_DEPTH)
    if effective_depth != args.max_depth:
        logger.emit("[限制] GitHub 目录深度安全上限 " + str(effective_depth) + "，已忽略配置值 " + str(args.max_depth), 0)
    try:
        for repo in load_repos(args):
            logger.emit("[仓库] 开始扫描 | " + repo, 0, current_repo=repo, repositories_delta=1)
            try:
                profiles = sink.source_profiles(repo)
                if profiles:
                    logger.emit("[画像] 已加载历史来源画像 " + str(len(profiles)) + " 条 | " + repo, 0)
                all_findings.extend(
                    crawl_repo(
                        client,
                        repo,
                        args.max_files,
                        args.max_bytes,
                        args.max_pages,
                        effective_depth,
                        args.workers,
                        sink.consume,
                        logger,
                        profiles,
                        sink.record_source_result,
                    )
                )
            except Exception as exc:
                failed += 1
                logger.emit("[失败] 仓库扫描失败 | " + repo + " | " + readable_error(exc), 0, failed_requests_delta=1)
        if not args.no_resolve_subscriptions:
            all_findings.extend(
                resolve_subscriptions(
                    client,
                    all_findings,
                    args.max_subscriptions,
                    args.subscription_depth,
                    args.max_bytes,
                    sink.consume,
                    logger,
                    min(args.workers, 4),
                )
            )
    finally:
        logger.emit_summary(failed)
        sink.close()
    findings = deduplicate(all_findings)
    print(json.dumps({
        "nodes": sum(item.kind == "node" for item in findings),
        "links": sum(item.kind in ("link", "subscription_link") for item in findings),
        "subscription_links": sum(item.kind == "subscription_link" for item in findings),
    }, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
