"""Maintenance file overview helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from app_config import CONFIG
from node_database import NodeDatabase


def directory_file_summary(path: Path, pattern: str = "*") -> Dict[str, int]:
    if not path.exists():
        return {"files": 0, "bytes": 0}
    files = [item for item in path.glob(pattern) if item.is_file()]
    total = 0
    for item in files:
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return {"files": len(files), "bytes": total}


def runtime_log_summary() -> Dict[str, int]:
    files = []
    if CONFIG.runtime_log.exists():
        files.append(CONFIG.runtime_log)
    files.extend(CONFIG.runtime_log.parent.glob(CONFIG.runtime_log.name + ".*"))
    total = 0
    for item in files:
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return {
        "files": len(files),
        "bytes": total,
        "max_bytes": int(CONFIG.runtime_log_max_bytes),
        "backup_count": int(CONFIG.runtime_log_backup_count),
    }


def maintenance_file_overview(root: Path) -> Dict[str, Dict[str, int]]:
    reports_dir = root / "data" / "reports"
    return {
        "runtime_logs": runtime_log_summary(),
        "acceptance_reports": directory_file_summary(reports_dir, "acceptance-*"),
    }


def maintenance_overview_with_files(database: NodeDatabase, root: Path) -> Dict[str, object]:
    overview = database.maintenance_overview()
    overview["files"] = maintenance_file_overview(root)
    return overview
