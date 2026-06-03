#!/usr/bin/env python3
"""Runtime configuration for the node dashboard service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def env_int(name: str, default: int, minimum: int = 1, maximum: int = 65535) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "")
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class AppConfig:
    root: Path
    host: str
    port: int
    admin_base_path: str
    database: Path
    web_root: Path
    log_dir: Path
    runtime_log: Path
    runtime_log_max_bytes: int
    log_buffer_size: int
    task_stop_timeout: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        root = env_path("HUAGE_ROOT", ROOT)
        log_dir = env_path("HUAGE_LOG_DIR", root / "data" / "logs")
        return cls(
            root=root,
            host=os.environ.get("HUAGE_HOST", "127.0.0.1"),
            port=env_int("HUAGE_PORT", 8765),
            admin_base_path=normalize_base_path(os.environ.get("HUAGE_ADMIN_BASE_PATH", "/adminhuage")),
            database=env_path("HUAGE_DATABASE", root / "data" / "nodes.db"),
            web_root=env_path("HUAGE_WEB_ROOT", root / "web"),
            log_dir=log_dir,
            runtime_log=env_path("HUAGE_RUNTIME_LOG", log_dir / "runtime.log"),
            runtime_log_max_bytes=env_int("HUAGE_RUNTIME_LOG_MAX_BYTES", 10 * 1024 * 1024, 1024 * 1024, 1024 * 1024 * 1024),
            log_buffer_size=env_int("HUAGE_LOG_BUFFER_SIZE", 1200, 100, 100000),
            task_stop_timeout=env_int("HUAGE_TASK_STOP_TIMEOUT", 3, 1, 120),
        )


def normalize_base_path(value: str) -> str:
    value = (value or "/adminhuage").strip()
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/") or "/adminhuage"


CONFIG = AppConfig.from_env()
