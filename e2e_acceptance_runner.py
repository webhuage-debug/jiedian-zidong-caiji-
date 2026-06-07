#!/usr/bin/env python3
"""End-to-end acceptance runner that drives the existing web APIs.

This script intentionally does not reimplement collection, validation,
subscription, conversion, or bot logic. It only acts like an operator:
start existing tasks, poll existing status, simulate existing bot messages,
redeem public subscriptions, call the existing Sub-Store conversion endpoint,
and write a report.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from node_database import NodeDatabase


TARGET_WEIGHTS = [
    ("clash-verge", 35),
    ("v2rayng", 30),
    ("shadowrocket", 20),
    ("sing-box", 10),
    ("surge", 5),
]

NODE_PREFIXES = (
    "vmess://",
    "vless://",
    "trojan://",
    "ss://",
    "ssr://",
    "socks://",
    "hysteria://",
    "hysteria2://",
    "hy2://",
)


class ApiError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: str):
        super().__init__(f"{method} {url} failed with HTTP {status}: {body[:500]}")
        self.method = method
        self.url = url
        self.status = status
        self.body = body


@dataclass
class ApiClient:
    base_url: str
    admin_path: str
    username: str
    password: str
    timeout: int = 60

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.admin_path = "/" + self.admin_path.strip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def admin_url(self, path: str) -> str:
        return self.base_url + self.admin_path + path

    def public_url(self, path: str) -> str:
        return self.base_url + path

    def login(self) -> dict[str, Any]:
        return self.post("/api/login", {"username": self.username, "password": self.password})

    def get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(self.admin_url(path), headers={"Accept": "application/json"})
        return self._json_request(request)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.admin_url(path),
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return self._json_request(request)

    def post_public_text(self, path: str, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.public_url(path),
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "text/plain"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise ApiError("POST", self.public_url(path), exc.code, body_text) from exc

    def _json_request(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise ApiError(request.get_method(), request.full_url, exc.code, body_text) from exc
        return json.loads(raw or "{}")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def emit_event(message: str, **extra: Any) -> None:
    event = {"message": message, "visible": True, **extra}
    print("@event " + json.dumps(event, ensure_ascii=False), flush=True)


def safe_b64decode(text: str) -> str:
    compact = "".join(text.strip().split())
    padding = "=" * ((4 - len(compact) % 4) % 4)
    try:
        return base64.b64decode((compact + padding).encode("utf-8"), validate=False).decode("utf-8", errors="replace")
    except Exception:
        return ""


def count_node_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip().startswith(NODE_PREFIXES))


def choose_target() -> str:
    ids = [item[0] for item in TARGET_WEIGHTS]
    weights = [item[1] for item in TARGET_WEIGHTS]
    return random.choices(ids, weights=weights, k=1)[0]


def target_plan(rounds: int) -> list[str]:
    required = [item[0] for item in TARGET_WEIGHTS]
    random.shuffle(required)
    if rounds <= len(required):
        return required[:rounds]
    return required + [choose_target() for _ in range(rounds - len(required))]


def database_stats(client: ApiClient) -> dict[str, Any]:
    return client.get("/api/status").get("database", {})


def wait_for_task_idle(client: ApiClient, task_name: str, poll_seconds: int, max_wait_seconds: int) -> None:
    deadline = time.monotonic() + max_wait_seconds
    while time.monotonic() < deadline:
        status = client.get("/api/status")
        task = ((status.get("tasks") or {}).get(task_name) or {})
        if not task.get("running"):
            return
        time.sleep(poll_seconds)
    raise TimeoutError(f"{task_name} did not stop within {max_wait_seconds}s")


def collect_until(client: ApiClient, target_nodes: int, poll_seconds: int, max_wait_seconds: int) -> dict[str, Any]:
    start = database_stats(client)
    if int(start.get("total_nodes") or 0) >= target_nodes:
        return {"skipped": True, "before": start, "after": start, "reason": "target already reached"}
    client.post("/api/collector/start", {
        "workers": 5,
        "max_depth": 8,
        "delay": 1.0,
        "delay_jitter": 0.5,
        "log_level": "detail",
    })
    deadline = time.monotonic() + max_wait_seconds
    last = start
    while time.monotonic() < deadline:
        last = database_stats(client)
        if int(last.get("total_nodes") or 0) >= target_nodes:
            client.post("/api/collector/stop", {})
            wait_for_task_idle(client, "collector", poll_seconds, 120)
            return {"skipped": False, "before": start, "after": database_stats(client), "reason": "target reached"}
        time.sleep(poll_seconds)
    return {"skipped": False, "before": start, "after": last, "reason": "timeout"}


def validate_until(client: ApiClient, target_valid_nodes: int, poll_seconds: int, max_wait_seconds: int) -> dict[str, Any]:
    start = database_stats(client)
    if int(start.get("valid_nodes") or 0) >= target_valid_nodes:
        return {"skipped": True, "before": start, "after": start, "reason": "target already reached"}
    batch_limit = min(max(100, target_valid_nodes * 5), 300)

    def start_validator() -> None:
        client.post("/api/validator/start", {
            "workers": 10,
            "limit": batch_limit,
            "rounds": 3,
            "timeout": 8,
            "prefer_asia": True,
        })

    start_validator()
    batch_before_valid = int(start.get("valid_nodes") or 0)
    no_yield_batches = 0
    deadline = time.monotonic() + max_wait_seconds
    last = start
    while time.monotonic() < deadline:
        last = database_stats(client)
        current_valid = int(last.get("valid_nodes") or 0)
        if current_valid >= target_valid_nodes:
            client.post("/api/validator/stop", {})
            wait_for_task_idle(client, "validator", poll_seconds, 180)
            return {"skipped": False, "before": start, "after": database_stats(client), "reason": "target reached"}
        task = ((client.get("/api/status").get("tasks") or {}).get("validator") or {})
        if not task.get("running") and current_valid < target_valid_nodes:
            pending = int(last.get("pending_nodes") or last.get("total_nodes") or 0)
            if pending <= 0:
                return {
                    "skipped": False,
                    "before": start,
                    "after": last,
                    "reason": "pending exhausted before target reached",
                    "batch_limit": batch_limit,
                    "no_yield_batches": no_yield_batches,
                }
            if current_valid <= batch_before_valid:
                no_yield_batches += 1
            else:
                no_yield_batches = 0
            if no_yield_batches >= 3:
                return {
                    "skipped": False,
                    "before": start,
                    "after": last,
                    "reason": "no valid yield after 3 batches",
                    "batch_limit": batch_limit,
                    "no_yield_batches": no_yield_batches,
                }
            batch_before_valid = current_valid
            start_validator()
        time.sleep(poll_seconds)
    return {"skipped": False, "before": start, "after": last, "reason": "timeout", "batch_limit": batch_limit}


def bot_claim(client: ApiClient, user_id: str, username: str, keyword: str, code: str) -> dict[str, Any]:
    group = client.post("/api/bot/simulate", {
        "text": keyword,
        "chat_type": "group",
        "chat_id": "-100001",
        "user_id": user_id,
        "username": username,
    })
    private_start = client.post("/api/bot/simulate", {
        "text": "/start claim",
        "chat_type": "private",
        "chat_id": user_id,
        "user_id": user_id,
        "username": username,
    })
    private_code = client.post("/api/bot/simulate", {
        "text": code,
        "chat_type": "private",
        "chat_id": user_id,
        "user_id": user_id,
        "username": username,
    })
    result = private_code.get("result") or {}
    subscription = result.get("subscription") or {}
    return {
        "group": group.get("result"),
        "private_start": private_start.get("result"),
        "claim": result,
        "subscription": subscription,
        "token": subscription.get("token") or "",
    }


def convert_and_check(client: ApiClient, target: str, raw_nodes: str) -> dict[str, Any]:
    started = time.monotonic()
    response = client.post("/api/subscription-converter/convert", {
        "backend_url": "http://127.0.0.1:3001",
        "profile_name": "sub",
        "export_limit": 100,
        "prefer_asia": True,
        "target": target,
        "input_mode": "custom",
        "input_type": "mixed",
        "content": raw_nodes,
    })
    content = str(response.get("content") or "")
    decoded = safe_b64decode(content)
    checks = {
        "non_empty": bool(content.strip()),
        "output_bytes": len(content.encode("utf-8")),
        "latency_ms": round((time.monotonic() - started) * 1000, 2),
    }
    if target == "clash-verge":
        checks["format_ok"] = "proxies:" in content
    elif target == "sing-box":
        checks["format_ok"] = '"outbounds"' in content or "'outbounds'" in content
    elif target == "surge":
        checks["format_ok"] = bool(content.strip())
    elif target in ("v2rayng", "shadowrocket"):
        checks["format_ok"] = count_node_lines(decoded) > 0 or content.strip().startswith(NODE_PREFIXES) or bool(content.strip())
    else:
        checks["format_ok"] = bool(content.strip())
    checks["ok"] = bool(checks["non_empty"] and checks["format_ok"])
    return {"target": target, "checks": checks, "response_target": response.get("target")}


def run_claim_rounds(
    client: ApiClient,
    rounds: int,
    rate_per_minute: int,
    keyword: str,
    code: str,
    cleanup_subscriptions: bool,
) -> list[dict[str, Any]]:
    results = []
    interval = 60.0 / max(1, rate_per_minute)
    targets = target_plan(rounds)
    for index in range(rounds):
        started = time.monotonic()
        user_id = "accept_" + datetime.now().strftime("%H%M%S") + "_" + str(index)
        target = targets[index]
        item: dict[str, Any] = {
            "index": index + 1,
            "user_id": user_id,
            "target": target,
            "started_at": now_text(),
            "ok": False,
        }
        try:
            claim = bot_claim(client, user_id, "fan_" + str(index), keyword, code)
            token = str(claim.get("token") or "")
            item["token"] = token
            item["claim_status"] = (claim.get("claim") or {}).get("status")
            if not token:
                item["error"] = "bot did not return subscription token"
            else:
                browser_client_id = user_id + "_browser"
                item["browser_client_id"] = browser_client_id
                subscription = client.post_public_text("/sub/" + token, {"code": code, "client_id": browser_client_id})
                raw_nodes = safe_b64decode(subscription)
                node_count = count_node_lines(raw_nodes)
                item["subscription_bytes"] = len(subscription.encode("utf-8"))
                item["raw_node_count"] = node_count
                if node_count <= 0:
                    item["error"] = "subscription has no real node uri"
                else:
                    conversion = convert_and_check(client, target, raw_nodes)
                    item["conversion"] = conversion
                    item["ok"] = bool(conversion["checks"]["ok"])
        except Exception as exc:
            item["error"] = str(exc)
        finally:
            token = str(item.get("token") or "")
            if cleanup_subscriptions and token:
                try:
                    client.post("/api/subscriptions/" + urllib.parse.quote(token, safe="") + "/delete", {})
                    item["cleanup_deleted"] = True
                except Exception as exc:
                    item["cleanup_deleted"] = False
                    item["cleanup_error"] = str(exc)
        item["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        results.append(item)
        emit_event(
            f"[验收] 第 {index + 1}/{rounds} 次 | {target} | {'成功' if item.get('ok') else '失败'} | 节点 {item.get('raw_node_count', 0)}",
            target=target,
            acceptance_total_delta=1,
            acceptance_success_delta=1 if item.get("ok") else 0,
            acceptance_failed_delta=0 if item.get("ok") else 1,
        )
        sleep_for = interval - (time.monotonic() - started)
        if sleep_for > 0 and index + 1 < rounds:
            time.sleep(sleep_for)
    return results


def summarize_claims(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_target: dict[str, dict[str, int]] = {}
    for item in items:
        target = str(item.get("target") or "unknown")
        bucket = by_target.setdefault(target, {"total": 0, "success": 0, "failed": 0})
        bucket["total"] += 1
        if item.get("ok"):
            bucket["success"] += 1
        else:
            bucket["failed"] += 1
    return {
        "total": len(items),
        "success": sum(1 for item in items if item.get("ok")),
        "failed": sum(1 for item in items if not item.get("ok")),
        "by_target": by_target,
    }


def write_report(report: dict[str, Any]) -> Path:
    reports_dir = Path("data") / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = reports_dir / f"acceptance-{stamp}.json"
    md_path = reports_dir / f"acceptance-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["claim_summary"]
    lines = [
        "# 端到端真实验收报告",
        "",
        f"- 开始时间：{report['started_at']}",
        f"- 结束时间：{report['finished_at']}",
        f"- 领取总数：{summary['total']}",
        f"- 成功：{summary['success']}",
        f"- 失败：{summary['failed']}",
        "",
        "## 随机格式结果",
    ]
    for target, stats in sorted(summary["by_target"].items()):
        lines.append(f"- {target}: 总数 {stats['total']}，成功 {stats['success']}，失败 {stats['failed']}")
    lines.extend([
        "",
        "## 数据库统计",
        "",
        "```json",
        json.dumps(report.get("final_database", {}), ensure_ascii=False, indent=2),
        "```",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def record_acceptance_daily_stats(report: dict[str, Any]) -> None:
    summary = report.get("claim_summary") or {}
    claims = report.get("claims") or []
    stat_date = str(report.get("finished_at") or now_text())[:10]
    latencies = [int(float(item.get("latency_ms") or 0)) for item in claims]
    with NodeDatabase(Path("data") / "nodes.db") as database:
        database.record_daily_ops_stat("acceptance", "total", int(summary.get("total") or 0), sum(latencies), max(latencies, default=0), stat_date)
        database.record_daily_ops_stat("acceptance", "success", int(summary.get("success") or 0), 0, 0, stat_date)
        database.record_daily_ops_stat("acceptance", "failed", int(summary.get("failed") or 0), 0, 0, stat_date)
        for target, stats in (summary.get("by_target") or {}).items():
            stats = stats or {}
            database.record_daily_ops_stat("acceptance_target", str(target) + ":total", int(stats.get("total") or 0), 0, 0, stat_date)
            database.record_daily_ops_stat("acceptance_target", str(target) + ":success", int(stats.get("success") or 0), 0, 0, stat_date)
            database.record_daily_ops_stat("acceptance_target", str(target) + ":failed", int(stats.get("failed") or 0), 0, 0, stat_date)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real E2E acceptance through existing Huage web APIs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--admin-path", default="adminhuage")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin888")
    parser.add_argument("--collect-target", type=int, default=20000)
    parser.add_argument("--valid-target", type=int, default=100)
    parser.add_argument("--claim-rounds", type=int, default=30)
    parser.add_argument("--claim-rate-per-minute", type=int, default=30)
    parser.add_argument("--keyword", default="我要节点")
    parser.add_argument("--code", default="")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--collect-max-wait-seconds", type=int, default=6 * 60 * 60)
    parser.add_argument("--validate-max-wait-seconds", type=int, default=2 * 60 * 60)
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--keep-test-subscriptions", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Run a short non-destructive smoke round.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.smoke:
        args.collect_target = 1
        args.valid_target = 1
        args.claim_rounds = min(args.claim_rounds, 5)
        args.collect_max_wait_seconds = min(args.collect_max_wait_seconds, 300)
        args.validate_max_wait_seconds = min(args.validate_max_wait_seconds, 300)
    client = ApiClient(args.base_url, args.admin_path, args.username, args.password)
    started_at = now_text()
    client.login()
    claim_config = client.get("/api/claim-code/config").get("config") or {}
    code = args.code or str(claim_config.get("code") or "")
    if not code:
        raise RuntimeError("claim code is empty; configure claim code first or pass --code")

    report: dict[str, Any] = {
        "started_at": started_at,
        "base_url": args.base_url,
        "mode": "smoke" if args.smoke else "full",
        "initial_database": database_stats(client),
    }
    if args.skip_collect:
        report["collect"] = {"skipped": True, "reason": "skip-collect"}
    else:
        report["collect"] = collect_until(client, args.collect_target, args.poll_seconds, args.collect_max_wait_seconds)
    if args.skip_validate:
        report["validate"] = {"skipped": True, "reason": "skip-validate"}
    else:
        report["validate"] = validate_until(client, args.valid_target, args.poll_seconds, args.validate_max_wait_seconds)
    report["converter_health"] = client.post("/api/subscription-converter/health", {"backend_url": "http://127.0.0.1:3001"}).get("health")
    claims = run_claim_rounds(
        client,
        args.claim_rounds,
        args.claim_rate_per_minute,
        args.keyword,
        code,
        not args.keep_test_subscriptions,
    )
    report["claims"] = claims
    report["claim_summary"] = summarize_claims(claims)
    report["final_database"] = database_stats(client)
    report["finished_at"] = now_text()
    report_path = write_report(report)
    record_acceptance_daily_stats(report)
    print(str(report_path))
    print(json.dumps(report["claim_summary"], ensure_ascii=False, indent=2))
    return 0 if report["claim_summary"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
