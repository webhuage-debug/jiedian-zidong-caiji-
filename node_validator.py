#!/usr/bin/env python3
"""Validate SQLite proxy nodes by routing strict probes through Xray."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from node_database import NodeDatabase
from geoip_resolver import GeoIPResolver


DEFAULT_MAX_BATCH = 50
SUPPORTED = {"vless", "vmess", "trojan", "ss", "socks", "socks5"}
PROXY_IPS_RE = re.compile(r"出口 ([^;]+)")
INVALID_STATUS = "无效"
VALID_STATUS = "有效"


def configure_text_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def decode_b64(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")


def first(query: Dict[str, list], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def stream_settings(query: Dict[str, list]) -> dict:
    network = first(query, "type", first(query, "net", "tcp"))
    security = first(query, "security")
    settings = {"network": network}
    if security in ("tls", "reality"):
        settings["security"] = security
        target = {
            "serverName": first(query, "sni"),
            "fingerprint": first(query, "fp"),
            "allowInsecure": first(query, "allowInsecure") in ("1", "true"),
        }
        if security == "reality":
            target.update({
                "publicKey": first(query, "pbk"),
                "shortId": first(query, "sid"),
                "spiderX": first(query, "spx", "/"),
            })
        settings[security + "Settings"] = {key: value for key, value in target.items() if value not in ("", False)}
    if network == "ws":
        ws = {"path": first(query, "path", "/")}
        if first(query, "host"):
            ws["headers"] = {"Host": first(query, "host")}
        settings["wsSettings"] = ws
    elif network == "grpc":
        settings["grpcSettings"] = {"serviceName": first(query, "serviceName")}
    elif network == "xhttp":
        settings["xhttpSettings"] = {
            key: value for key, value in {
                "path": first(query, "path", "/"),
                "host": first(query, "host"),
                "mode": first(query, "mode"),
            }.items() if value
        }
    return settings


def parse_standard(node: str, scheme: str) -> dict:
    parsed = urllib.parse.urlsplit(node)
    if not parsed.hostname or not parsed.port:
        raise ValueError("missing server or port")
    query = urllib.parse.parse_qs(parsed.query)
    credential = urllib.parse.unquote(parsed.username or "")
    if scheme == "vless":
        user = {"id": credential, "encryption": first(query, "encryption", "none")}
        if first(query, "flow"):
            user["flow"] = first(query, "flow")
        settings = {"vnext": [{"address": parsed.hostname, "port": parsed.port, "users": [user]}]}
    elif scheme == "trojan":
        settings = {"servers": [{"address": parsed.hostname, "port": parsed.port, "password": credential}]}
    else:
        settings = {"servers": [{"address": parsed.hostname, "port": parsed.port}]}
        if credential:
            settings["servers"][0]["users"] = [{"user": credential, "pass": urllib.parse.unquote(parsed.password or "")}]
    return {"protocol": "socks" if scheme == "socks5" else scheme, "settings": settings, "streamSettings": stream_settings(query)}


def parse_vmess(node: str) -> dict:
    payload = json.loads(decode_b64(node.split("://", 1)[1].split("#", 1)[0]))
    query = {
        "type": [str(payload.get("net", "tcp"))],
        "security": [str(payload.get("tls", ""))],
        "sni": [str(payload.get("sni") or payload.get("host") or "")],
        "host": [str(payload.get("host", ""))],
        "path": [str(payload.get("path", ""))],
    }
    user = {"id": payload["id"], "alterId": int(payload.get("aid", 0)), "security": payload.get("scy", "auto")}
    settings = {"vnext": [{"address": payload["add"], "port": int(payload["port"]), "users": [user]}]}
    return {"protocol": "vmess", "settings": settings, "streamSettings": stream_settings(query)}


def parse_ss(node: str) -> dict:
    value = node.split("://", 1)[1].split("#", 1)[0]
    value = value.split("?", 1)[0]
    if "@" in value:
        userinfo, address = value.rsplit("@", 1)
        secret = decode_b64(userinfo) if ":" not in userinfo else urllib.parse.unquote(userinfo)
    else:
        secret, address = decode_b64(value).rsplit("@", 1)
    method, password = secret.split(":", 1)
    parsed = urllib.parse.urlsplit("//" + address)
    if not parsed.hostname or not parsed.port:
        raise ValueError("missing server or port")
    settings = {"servers": [{"address": parsed.hostname, "port": parsed.port, "method": method, "password": password}]}
    return {"protocol": "shadowsocks", "settings": settings}


def outbound_for(node: str) -> dict:
    scheme = node.split("://", 1)[0].lower()
    if scheme not in SUPPORTED:
        raise ValueError("unsupported by Xray: " + scheme)
    if scheme == "vmess":
        return parse_vmess(node)
    if scheme == "ss":
        return parse_ss(node)
    return parse_standard(node, scheme)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def config_for(node: str, port: int) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks", "settings": {"udp": False}}],
        "outbounds": [outbound_for(node)],
    }


def safe_node_summary(node: str) -> str:
    scheme = (node.split("://", 1)[0] or "node").lower()
    digest = hashlib.sha256(node.encode("utf-8", errors="replace")).hexdigest()[:8]
    host = ""
    port = ""
    try:
        if scheme == "vmess":
            payload = json.loads(decode_b64(node.split("://", 1)[1].split("#", 1)[0]))
            host = str(payload.get("add") or "")
            port = str(payload.get("port") or "")
        elif scheme == "ss" and "@" not in node.split("://", 1)[1].split("#", 1)[0]:
            decoded = decode_b64(node.split("://", 1)[1].split("#", 1)[0])
            parsed = urllib.parse.urlsplit("//" + decoded.rsplit("@", 1)[1])
            host = parsed.hostname or ""
            port = str(parsed.port or "")
        else:
            parsed = urllib.parse.urlsplit(node)
            host = parsed.hostname or ""
            port = str(parsed.port or "")
    except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError, IndexError):
        pass
    parts = ["protocol=" + scheme, "name_hash=" + digest]
    if host:
        parts.insert(1, "host=" + host)
    if port:
        parts.insert(2 if host else 1, "port=" + port)
    return " ".join(parts)


def validation_reason_bucket(reason: str) -> str:
    lowered = reason.lower()
    if "timeout" in lowered or "timed out" in lowered or "超时" in reason:
        return "timeout"
    if "tls" in lowered:
        return "tls_error"
    if "connection reset" in lowered or "recv failure" in lowered or "reset by peer" in lowered:
        return "connection_reset"
    if "missing server" in lowered or "unsupported by xray" in lowered or "json" in lowered or "配置错误" in reason:
        return "parse_error"
    if "xray 调用失败" in reason or "xray 启动失败" in reason or "exception" in lowered or "traceback" in lowered:
        return "exception"
    return "invalid"


def resolve_xray_path(path: Path) -> Path:
    candidates = []
    if sys.platform.startswith("win"):
        if path.suffix.lower() == ".exe":
            candidates.append(path)
        else:
            candidates.append(path.with_name(path.name + ".exe"))
            candidates.append(path.parent / "xray.exe")
        candidates.append(path)
        candidates.append(path.parent / "xray")
    else:
        candidates.append(path)
        if path.suffix.lower() != ".exe":
            candidates.append(path.with_name(path.name + ".exe"))
        if path.name.lower() != "xray":
            candidates.append(path.parent / "xray")
            candidates.append(path.parent / "xray.exe")
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "未找到 Xray 可执行文件。请在 Linux 放置 tools/xray/xray，"
        "或在 Windows 放置 tools/xray/xray.exe，也可通过 --xray 指定路径。"
    )


def curl_trace_ip(timeout: int) -> str:
    result = subprocess.run(
        [
            "curl", "-sS", "-L", "--noproxy", "*",
            "--connect-timeout", str(timeout), "--max-time", str(timeout),
            "https://www.cloudflare.com/cdn-cgi/trace",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout + 2,
    )
    if result.returncode:
        raise RuntimeError("无法获取本机直连出口 IP: " + result.stderr.strip()[-300:])
    for line in result.stdout.splitlines():
        if line.startswith("ip="):
            return line[3:].strip()
    raise RuntimeError("本机直连 Cloudflare trace 未返回出口 IP")


def run_probe(port: int, probe_url: str, timeout: int) -> Tuple[bool, str, Optional[str]]:
    probe = subprocess.run(
        [
            "curl", "-sS", "-L",
            "--noproxy", "",
            "--proxy", "socks5h://127.0.0.1:" + str(port),
            "--connect-timeout", str(timeout), "--max-time", str(timeout),
            "-w", "\n%{http_code}", probe_url,
        ],
        capture_output=True, timeout=timeout + 2,
    )
    body, _, status_bytes = probe.stdout.rpartition(b"\n")
    status = status_bytes.decode("ascii", errors="replace")
    if probe.returncode:
        return False, probe.stderr.decode("utf-8", errors="replace").strip()[-300:], None
    if status in ("", "000") or not status.startswith("2"):
        return False, "HTTP " + status, None
    if "cdn-cgi/trace" in probe_url and b"ip=" not in body:
        return False, "Cloudflare trace 未返回出口 IP", None
    if "__down?bytes=" in probe_url:
        expected = int(urllib.parse.parse_qs(urllib.parse.urlsplit(probe_url).query)["bytes"][0])
        if len(body) < expected:
            return False, "下载内容不足 " + str(expected) + " 字节", None
    trace_ip = None
    if "cdn-cgi/trace" in probe_url:
        for line in body.splitlines():
            if line.startswith(b"ip="):
                trace_ip = line[3:].decode("ascii", errors="replace").strip()
                break
    return True, "HTTP " + status, trace_ip


def validate_node(
    xray: Path,
    node: str,
    probe_urls: Sequence[str],
    timeout: int,
    direct_ip: str,
    rounds: int,
    round_delay: float,
) -> Tuple[str, str, float]:
    started = time.monotonic()
    try:
        port = free_port()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "xray-config.json"
            config_path.write_text(json.dumps(config_for(node, port)), encoding="utf-8")
            checked = subprocess.run(
                [str(xray), "run", "-test", "-c", str(config_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if checked.returncode:
                return "无效", "Xray 配置错误: " + (checked.stderr or checked.stdout).strip()[-300:], time.monotonic() - started
            process = subprocess.Popen(
                [str(xray), "run", "-c", str(config_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                time.sleep(0.25)
                if process.poll() is not None:
                    return "无效", "Xray 启动失败: " + (process.stderr.read() if process.stderr else "")[-300:], time.monotonic() - started
                proxy_ips = set()
                for round_number in range(1, rounds + 1):
                    for probe_url in probe_urls:
                        ok, reason, trace_ip = run_probe(port, probe_url, timeout)
                        if not ok:
                            return "无效", "第 " + str(round_number) + " 轮 " + probe_url + " => " + reason, time.monotonic() - started
                        if trace_ip:
                            proxy_ips.add(trace_ip)
                    if round_number < rounds and round_delay:
                        time.sleep(round_delay)
                if not proxy_ips:
                    return "无效", "未获取代理出口 IP", time.monotonic() - started
                if direct_ip in proxy_ips:
                    return "无效", "代理出口 IP 与本机直连 IP 相同: " + direct_ip, time.monotonic() - started
                return "有效", "稳定代理检查通过: " + str(rounds) + " 轮; 出口 " + ",".join(sorted(proxy_ips)), time.monotonic() - started
            finally:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
    except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return "无效", str(exc), time.monotonic() - started
    except subprocess.TimeoutExpired:
        return "无效", "验证超时", time.monotonic() - started
    except OSError as exc:
        return "无效", "Xray 调用失败: " + str(exc), time.monotonic() - started


def proxy_ips_from_reason(reason: str) -> str:
    match = PROXY_IPS_RE.search(reason)
    return match.group(1) if match else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xray", type=Path, default=Path("tools/xray/xray"))
    parser.add_argument("--database", type=Path, default=Path("data/nodes.db"))
    parser.add_argument("--limit", type=int, default=50, help="batch size, hard-capped at 50")
    parser.add_argument("--max-batch", type=int, default=DEFAULT_MAX_BATCH, help="maximum allowed batch size")
    parser.add_argument("--protocol", action="append", help="only validate this URI scheme; repeat for multiple schemes")
    parser.add_argument("--random", action="store_true", help="randomly sample eligible nodes")
    parser.add_argument("--revalidate", action="store_true", help="include nodes that already have a validation result")
    parser.add_argument("--valid-only", action="store_true", help="recheck nodes from the valid-node pool and prune failures")
    parser.add_argument("--prefer-asia", action="store_true", help="when rechecking valid nodes, validate Asian candidates first and fall back globally")
    parser.add_argument("--seed", type=int, help="random seed for reproducible sampling")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--workers", type=int, default=10, help="concurrent Xray validators")
    parser.add_argument("--rounds", type=int, default=3, help="required successful validation rounds")
    parser.add_argument("--round-delay", type=float, default=0.75, help="delay between validation rounds")
    parser.add_argument("--probe-url", action="append", help="strict probe URL; repeat to require multiple probes")
    return parser.parse_args()


def main() -> int:
    configure_text_streams()
    args = parse_args()
    if args.workers <= 0 or args.max_batch <= 0 or args.rounds <= 0 or args.round_delay < 0:
        raise SystemExit("--workers, --max-batch and --rounds must be positive; --round-delay must not be negative")
    try:
        xray_path = resolve_xray_path(args.xray)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    probe_urls = args.probe_url or [
        "https://www.google.com/generate_204",
        "https://www.cloudflare.com/cdn-cgi/trace",
        "https://speed.cloudflare.com/__down?bytes=32768",
    ]
    try:
        direct_ip = curl_trace_ip(args.timeout)
        print("本机直连出口 IP: " + direct_ip, flush=True)
    except RuntimeError as exc:
        direct_ip = ""
        print("本机直连出口 IP 获取失败，已降级继续验证: " + str(exc), flush=True)
    database = NodeDatabase(args.database)
    geoip = GeoIPResolver(xray_path.parent / "geoip.dat")
    protocols = {item.lower() for item in (args.protocol or [])}
    if args.valid_only:
        eligible = list(database.iter_valid_nodes(min(max(args.limit, 0), args.max_batch), args.prefer_asia))
    else:
        eligible = list(database.iter_nodes(sorted(protocols), args.revalidate))
    if args.random:
        random.Random(args.seed).shuffle(eligible)
    batch = eligible[:min(max(args.limit, 0), args.max_batch)]
    stats = {
        "batch": len(batch),
        "valid": 0,
        "invalid": 0,
        "timeout": 0,
        "tls_error": 0,
        "connection_reset": 0,
        "parse_error": 0,
        "exception": 0,
        "new_valid": 0,
    }
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    validate_node,
                    xray_path,
                    node,
                    probe_urls,
                    args.timeout,
                    direct_ip,
                    args.rounds,
                    args.round_delay,
                ): node
                for node in batch
            }
            for index, future in enumerate(as_completed(futures), 1):
                node = futures[future]
                try:
                    status, reason, seconds = future.result()
                except Exception as exc:
                    status, reason, seconds = INVALID_STATUS, "程序异常: " + str(exc), 0.0
                proxy_ips = proxy_ips_from_reason(reason)
                country = geoip.country_for_ips(proxy_ips) if status == VALID_STATUS else ""
                database.record_validation(node, status, reason, seconds, proxy_ips, country)
                if status == VALID_STATUS:
                    stats["valid"] += 1
                    if not args.valid_only:
                        stats["new_valid"] += 1
                else:
                    stats["invalid"] += 1
                    bucket = validation_reason_bucket(reason)
                    if bucket in stats:
                        stats[bucket] += 1
                print(f"[{index}/{len(batch)}] {status} {reason} | {safe_node_summary(node)}", flush=True)
    finally:
        database.close()
    elapsed = time.monotonic() - started
    print(
        "[验证汇总] batch={batch} valid={valid} invalid={invalid} timeout={timeout} "
        "tls_error={tls_error} connection_reset={connection_reset} parse_error={parse_error} "
        "exception={exception} new_valid={new_valid} elapsed={elapsed:.1f}s exit=0".format(
            elapsed=elapsed,
            **stats,
        ),
        flush=True,
    )
    print("本批完成: " + str(len(batch)) + " 条", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
