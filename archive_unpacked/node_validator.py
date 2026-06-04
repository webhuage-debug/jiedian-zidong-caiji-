#!/usr/bin/env python3
"""Validate SQLite proxy nodes by routing strict probes through Xray."""

from __future__ import annotations

import argparse
import base64
import json
import os
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


def safe_print(message: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    print(str(message).encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=True)


def default_xray_path() -> Path:
    path = Path("tools/xray/xray")
    exe_path = Path("tools/xray/xray.exe")
    if exe_path.exists():
        return exe_path
    if path.exists():
        return path
    return path


def decode_b64(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")


def first(query: Dict[str, list], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def curl_base_command() -> list:
    if os.name == "nt":
        return ["curl.exe", "--ssl-no-revoke", "-k"]
    return ["curl"]


def stream_settings(query: Dict[str, list]) -> dict:
    network = first(query, "type", first(query, "net", "tcp"))
    security = first(query, "security")
    settings = {"network": network}
    if security in ("tls", "reality"):
        settings["security"] = security
        target = {
            "serverName": first(query, "sni"),
            "fingerprint": first(query, "fp"),
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


def curl_trace_ip(timeout: int) -> str:
    result = subprocess.run(
        curl_base_command() + [
            "-sS", "-L", "--noproxy", "*",
            "--connect-timeout", str(timeout), "--max-time", str(timeout),
            "https://www.cloudflare.com/cdn-cgi/trace",
        ],
        capture_output=True, text=True, timeout=timeout + 2,
    )
    if result.returncode:
        raise RuntimeError("无法获取本机直连出口 IP: " + result.stderr.strip()[-300:])
    for line in result.stdout.splitlines():
        if line.startswith("ip="):
            return line[3:].strip()
    raise RuntimeError("本机直连 Cloudflare trace 未返回出口 IP")


def default_probe_urls() -> list:
    if os.name == "nt":
        return [
            "http://www.gstatic.com/generate_204",
            "http://ip-api.com/line/?fields=query",
        ]
    return [
        "https://www.google.com/generate_204",
        "https://www.cloudflare.com/cdn-cgi/trace",
        "https://speed.cloudflare.com/__down?bytes=32768",
    ]


def run_probe(port: int, probe_url: str, timeout: int) -> Tuple[bool, str, Optional[str]]:
    probe = subprocess.run(
        curl_base_command() + [
            "-sS", "-L",
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
    if "ip-api.com/line" in probe_url:
        candidate = body.decode("ascii", errors="ignore").strip().splitlines()[0] if body.strip() else ""
        if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", candidate):
            trace_ip = candidate
        else:
            return False, "ip-api 未返回代理出口 IP", None
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
    config_path = ""
    try:
        port = free_port()
        fd, config_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config_for(node, port), handle)
        checked = subprocess.run([str(xray), "run", "-test", "-c", config_path], capture_output=True, text=True, timeout=5)
        if checked.returncode:
            return "无效", "Xray 配置错误: " + (checked.stderr or checked.stdout).strip()[-300:], time.monotonic() - started
        process = subprocess.Popen([str(xray), "run", "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
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
            if direct_ip and direct_ip in proxy_ips:
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
    finally:
        if config_path:
            try:
                os.unlink(config_path)
            except OSError:
                pass


def proxy_ips_from_reason(reason: str) -> str:
    match = PROXY_IPS_RE.search(reason)
    return match.group(1) if match else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xray", type=Path, default=default_xray_path())
    parser.add_argument("--database", type=Path, default=Path("data/nodes.db"))
    parser.add_argument("--limit", type=int, default=50, help="batch size, hard-capped at 50")
    parser.add_argument("--max-batch", type=int, default=DEFAULT_MAX_BATCH, help="maximum allowed batch size")
    parser.add_argument("--protocol", action="append", help="only validate this URI scheme; repeat for multiple schemes")
    parser.add_argument("--random", action="store_true", help="randomly sample eligible nodes")
    parser.add_argument("--revalidate", action="store_true", help="include nodes that already have a validation result")
    parser.add_argument("--valid-only", action="store_true", help="recheck nodes that are currently valid")
    parser.add_argument("--asia-first", action="store_true", help="prefer Asian node candidates before global candidates")
    parser.add_argument("--seed", type=int, help="random seed for reproducible sampling")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--workers", type=int, default=10, help="concurrent Xray validators")
    parser.add_argument("--rounds", type=int, default=3, help="required successful validation rounds")
    parser.add_argument("--round-delay", type=float, default=0.75, help="delay between validation rounds")
    parser.add_argument("--probe-url", action="append", help="strict probe URL; repeat to require multiple probes")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers <= 0 or args.max_batch <= 0 or args.rounds <= 0 or args.round_delay < 0:
        raise SystemExit("--workers, --max-batch and --rounds must be positive; --round-delay must not be negative")
    probe_urls = args.probe_url or default_probe_urls()
    try:
        direct_ip = curl_trace_ip(args.timeout)
        safe_print("本机直连出口 IP: " + direct_ip)
    except RuntimeError as error:
        direct_ip = ""
        safe_print("无法获取本机直连出口 IP，继续验证节点: " + str(error))
    database = NodeDatabase(args.database)
    geoip = GeoIPResolver(args.xray.parent / "geoip.dat")
    protocols = {item.lower() for item in (args.protocol or [])}
    if args.valid_only:
        eligible = list(database.iter_valid_nodes_for_recheck(sorted(protocols)))
    elif args.asia_first:
        asia = list(database.iter_asia_candidate_nodes(sorted(protocols), args.revalidate))
        global_nodes = list(database.iter_nodes(sorted(protocols), args.revalidate))
        eligible = list(dict.fromkeys(asia + global_nodes))
    else:
        eligible = list(database.iter_nodes(sorted(protocols), args.revalidate))
    if args.random:
        random.Random(args.seed).shuffle(eligible)
    batch = eligible[:min(max(args.limit, 0), args.max_batch)]
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    validate_node,
                    args.xray,
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
                status, reason, seconds = future.result()
                proxy_ips = proxy_ips_from_reason(reason)
                country = geoip.country_for_ips(proxy_ips) if status == "有效" else ""
                database.record_validation(node, status, reason, seconds, proxy_ips, country)
                safe_print(f"[{index}/{len(batch)}] {status} {reason} {node}")
    finally:
        database.close()
    safe_print("本批完成: " + str(len(batch)) + " 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
