"""Acceptance task helpers used by the web dashboard."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List

from app_config import CONFIG


def build_acceptance_command(payload: dict, admin_base_path: str) -> List[str]:
    def int_value(data: dict, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(data.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    command = [
        sys.executable,
        "-u",
        "e2e_acceptance_runner.py",
        "--base-url",
        "http://127.0.0.1:" + str(CONFIG.port),
        "--admin-path",
        admin_base_path.strip("/"),
        "--collect-target",
        str(int_value(payload, "collect_target", 20000, 1, 1000000)),
        "--valid-target",
        str(int_value(payload, "valid_target", 100, 1, 100000)),
        "--claim-rounds",
        str(int_value(payload, "claim_rounds", 30, 1, 100000)),
        "--claim-rate-per-minute",
        str(int_value(payload, "claim_rate_per_minute", 30, 1, 10000)),
    ]
    if payload.get("skip_collect"):
        command.append("--skip-collect")
    if payload.get("skip_validate"):
        command.append("--skip-validate")
    if payload.get("smoke"):
        command.append("--smoke")
    if payload.get("keep_test_subscriptions"):
        command.append("--keep-test-subscriptions")
    keyword = str(payload.get("keyword") or "").strip()
    if keyword:
        command.extend(["--keyword", keyword])
    code = str(payload.get("code") or "").strip()
    if code:
        command.extend(["--code", code])
    return command


def load_acceptance_report(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    summary = data.get("claim_summary") or {}
    return {
        "file": path.name,
        "path": str(path),
        "started_at": data.get("started_at", ""),
        "finished_at": data.get("finished_at", ""),
        "mode": data.get("mode", ""),
        "summary": summary,
        "database": data.get("final_database") or {},
        "report": data,
    }


def acceptance_reports(root: Path, limit: int = 10) -> List[dict]:
    reports_dir = root / "data" / "reports"
    if not reports_dir.exists():
        return []
    items = sorted(reports_dir.glob("acceptance-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    reports = []
    for path in items[:limit]:
        report = load_acceptance_report(path)
        if report:
            reports.append(report)
    return reports


def cleanup_acceptance_reports(root: Path, config: dict) -> Dict[str, int]:
    reports_dir = root / "data" / "reports"
    if not reports_dir.exists():
        return {
            "acceptance_reports_deleted": 0,
            "acceptance_reports_bytes_deleted": 0,
            "acceptance_reports_failed_kept": 0,
        }
    now = time.time()
    success_days = max(1, int(config.get("acceptance_report_days", 7) or 7))
    failed_days = max(1, int(config.get("acceptance_failed_report_days", 30) or 30))
    max_success_files = max(10, int(config.get("acceptance_report_max_files", 300) or 300))
    json_files = sorted(
        reports_dir.glob("acceptance-*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    success_seen = 0
    deleted_files = 0
    deleted_bytes = 0
    failed_kept = 0
    for path in json_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        summary = payload.get("claim_summary") if isinstance(payload, dict) else {}
        failed_count = int((summary or {}).get("failed") or 0)
        is_failed = failed_count > 0 or bool(payload.get("errors")) or payload.get("ok") is False
        age_days = (now - path.stat().st_mtime) / 86400
        remove = False
        if is_failed:
            failed_kept += 1
            remove = age_days > failed_days
        else:
            success_seen += 1
            remove = age_days > success_days or success_seen > max_success_files
        if not remove:
            continue
        related = [path, path.with_suffix(".md")]
        for item in related:
            try:
                size = item.stat().st_size
                item.unlink()
            except OSError:
                continue
            deleted_files += 1
            deleted_bytes += size
    return {
        "acceptance_reports_deleted": deleted_files,
        "acceptance_reports_bytes_deleted": deleted_bytes,
        "acceptance_reports_failed_kept": failed_kept,
    }
