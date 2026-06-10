#!/usr/bin/env python3
"""Runtime log bus and subprocess task management for the dashboard."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import List, Optional

from app_config import CONFIG
from app_time import beijing_date, beijing_time


class LogBus:
    def __init__(self, size: int = 1200, log_file: Optional[Path] = None):
        self.events = deque(maxlen=size)
        self.sequence = 0
        self.condition = threading.Condition()
        self.log_file = log_file
        self.log_lock = threading.Lock()
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, source: str, message: str, level: str = "info") -> None:
        clean_message = message.rstrip()
        with self.condition:
            self.sequence += 1
            event = {
                "id": self.sequence,
                "time": beijing_time(),
                "source": source,
                "level": level,
                "message": clean_message,
            }
            self.events.append(event)
            self._append_file(event)
            self.condition.notify_all()

    def after(self, cursor: int) -> List[dict]:
        with self.condition:
            return [event for event in self.events if event["id"] > cursor]

    def clear(self) -> None:
        with self.condition:
            self.events.clear()
            self.condition.notify_all()

    def _append_file(self, event: dict) -> None:
        if not self.log_file:
            return
        line = (
            beijing_date() + " "
            + event["time"]
            + " [" + event["source"] + "] "
            + event["level"]
            + " | "
            + event["message"]
            + "\n"
        )
        try:
            with self.log_lock:
                self._rotate_file_if_needed()
                with self.log_file.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except OSError:
            return

    def _rotate_file_if_needed(self) -> None:
        if not self.log_file or not self.log_file.exists():
            return
        if self.log_file.stat().st_size < CONFIG.runtime_log_max_bytes:
            return
        backup_count = max(1, int(CONFIG.runtime_log_backup_count or 1))
        oldest = self.log_file.with_name(self.log_file.name + "." + str(backup_count))
        if oldest.exists():
            oldest.unlink()
        for index in range(backup_count - 1, 0, -1):
            source = self.log_file.with_name(self.log_file.name + "." + str(index))
            target = self.log_file.with_name(self.log_file.name + "." + str(index + 1))
            if source.exists():
                source.rename(target)
        self.log_file.rename(self.log_file.with_name(self.log_file.name + ".1"))


class ManagedTask:
    def __init__(self, name: str, log_bus: LogBus):
        self.name = name
        self.log_bus = log_bus
        self.stop_timeout = CONFIG.task_stop_timeout
        self.lock = threading.Lock()
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None
        self.progress = self.empty_progress()

    @staticmethod
    def empty_progress() -> dict:
        return {
            "current_repo": "",
            "current_url": "",
            "active_requests": 0,
            "repositories": 0,
            "directory_pages": 0,
            "candidate_files": 0,
            "fetched_files": 0,
            "no_node_files": 0,
            "skipped_dirs": 0,
            "failed_requests": 0,
            "parsed_nodes": 0,
            "inserted_nodes": 0,
            "duplicate_nodes": 0,
            "region_rejected": 0,
            "database_total": 0,
        }

    def status(self) -> dict:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return {
                "running": running,
                "pid": self.process.pid if running else None,
                "started_at": self.started_at if running else None,
                "progress": dict(self.progress),
            }

    def start(self, command: List[str]) -> bool:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return False
            self.process = subprocess.Popen(
                command,
                cwd=CONFIG.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=task_environment(),
                start_new_session=True,
            )
            self.started_at = time.time()
            self.progress = self.empty_progress()
            process = self.process
        self.log_bus.emit(self.name, "任务已启动，PID " + str(process.pid), "success")
        threading.Thread(target=self._read_output, args=(process,), daemon=True).start()
        return True

    def stop(self) -> bool:
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                return False
        self.log_bus.emit(self.name, "正在停止任务...", "warning")
        try:
            terminate_process(process)
        except ProcessLookupError:
            return False
        threading.Thread(target=self._force_stop, args=(process,), daemon=True).start()
        return True

    def wait_stopped(self, timeout: Optional[int] = None) -> None:
        with self.lock:
            process = self.process
        if process is None:
            return
        try:
            process.wait(timeout=timeout or self.stop_timeout)
        except subprocess.TimeoutExpired:
            return

    def _force_stop(self, process: subprocess.Popen) -> None:
        try:
            process.wait(timeout=self.stop_timeout)
        except subprocess.TimeoutExpired:
            self.log_bus.emit(self.name, "任务未及时退出，执行强制停止", "warning")
            try:
                kill_process(process)
            except ProcessLookupError:
                pass

    def _read_output(self, process: subprocess.Popen) -> None:
        if process.stdout:
            for line in process.stdout:
                message = line.rstrip()
                if message:
                    if message.startswith("@event "):
                        self._apply_event(message[7:])
                        continue
                    message = normalize_task_output(message)
                    if not message:
                        continue
                    level = task_output_level(message)
                    self.log_bus.emit(self.name, message, level)
        code = process.wait()
        with self.lock:
            if self.process is process:
                self.process = None
                self.started_at = None
                self.progress["active_requests"] = 0
        level = "success" if code == 0 else "warning"
        self.log_bus.emit(self.name, "任务已结束，退出码 " + str(code), level)

    def _apply_event(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            self.log_bus.emit(self.name, raw, "warning")
            return
        with self.lock:
            for key in ("current_repo", "current_url", "active_requests", "database_total"):
                if key in event:
                    self.progress[key] = event[key]
            for key in (
                "repositories", "directory_pages", "candidate_files", "fetched_files", "failed_requests",
                "parsed_nodes", "inserted_nodes", "duplicate_nodes", "region_rejected",
                "skipped_dirs", "no_node_files",
            ):
                delta = event.get(key + "_delta")
                if delta:
                    self.progress[key] += delta
        if not event.get("visible", True):
            return
        message = event.get("message", raw)
        level = task_output_level(message)
        self.log_bus.emit(self.name, message, level)


def task_environment() -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # Do not force PYTHONUTF8 on Windows. With the bundled Python under a
    # non-ASCII user profile, curl/certifi may receive a certificate path that
    # it cannot open, which makes GitHub collection fail with curl error 77.
    env.pop("PYTHONUTF8", None)
    return env


def terminate_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        process.terminate()
        return
    os.killpg(process.pid, signal.SIGTERM)


def kill_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        process.kill()
        return
    os.killpg(process.pid, signal.SIGKILL)


def summarize_network_error(message: str) -> str:
    if "curl: (28)" in message and "Operation timed out" in message:
        return "请求超时：在超时时间内没有收到数据"
    if "curl: (28)" in message and "Connection timed out" in message:
        return "连接超时：无法在超时时间内连接目标站点"
    if "Operation timed out" in message:
        return "请求超时"
    if "Connection timed out" in message:
        return "连接超时"
    if "Failed to perform" in message:
        return "请求执行失败"
    return message


def task_output_level(message: str) -> str:
    lowered = message.lower()
    hard_errors = (
        "traceback",
        "exception",
        "filenotfounderror",
        "database is locked",
        "no such table",
        "xray 可执行文件",
        "未找到 xray",
        "geoip.dat",
        "geosite.dat",
        "无法启动",
        "写库失败",
    )
    if any(item in lowered for item in hard_errors):
        return "error"
    soft_failures = (
        "无效",
        "timeout",
        "timed out",
        "tls",
        "connection reset",
        "recv failure",
        "curl:",
        "[失败]",
        "[跳过]",
        "验证汇总",
    )
    if any(item in lowered for item in soft_failures):
        return "warning"
    return "info"


def normalize_task_output(message: str) -> Optional[str]:
    if message.startswith("{") and '"nodes"' in message:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return message
        return (
            "采集汇总 | 节点 " + str(data.get("nodes", 0))
            + " | 链接 " + str(data.get("links", 0))
            + " | 订阅链接 " + str(data.get("subscription_links", 0))
        )
    fetched = re.search(r"INFO: Fetched \((\d+)\) <GET ([^>]+)>", message)
    if fetched:
        return None
    if "WARNING:" in message and "Proxy 'None' failed" in message:
        summary = summarize_network_error(message)
        if summary == message:
            summary = "当前连接未成功，稍后自动重试"
        return "底层请求失败，正在重试 | " + summary
    if "WARNING:" in message and ("Attempt" in message or "Retrying" in message):
        return "底层请求失败，正在重试 | " + summarize_network_error(message)
    if "ERROR:" in message and "Failed after" in message:
        return "底层请求最终失败 | " + summarize_network_error(message)
    return message
