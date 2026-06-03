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
        rotated = self.log_file.with_name(self.log_file.name + ".1")
        if rotated.exists():
            rotated.unlink()
        self.log_file.rename(rotated)


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
            "directory_pages": 0,
            "candidate_files": 0,
            "fetched_files": 0,
            "no_node_files": 0,
            "failed_requests": 0,
            "parsed_nodes": 0,
            "inserted_nodes": 0,
            "duplicate_nodes": 0,
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
            process_options = {
                "cwd": CONFIG.root,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "bufsize": 1,
            }
            if os.name == "nt":
                process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                process_options["start_new_session"] = True
            self.process = subprocess.Popen(command, **process_options)
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
        self._terminate_process(process, force=False)
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
            self._terminate_process(process, force=True)

    @staticmethod
    def _terminate_process(process: subprocess.Popen, force: bool) -> None:
        if os.name == "nt":
            if force:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                process.terminate()
            return
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
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
                    level = "error" if "error" in message.lower() or "失败" in message or "无效" in message else "info"
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
                "directory_pages", "candidate_files", "fetched_files", "failed_requests",
                "parsed_nodes", "inserted_nodes", "duplicate_nodes", "no_node_files",
            ):
                delta = event.get(key + "_delta")
                if delta:
                    self.progress[key] += delta
        if not event.get("visible", True):
            return
        message = event.get("message", raw)
        level = "error" if "[失败]" in message else "warning" if "[跳过]" in message else "info"
        self.log_bus.emit(self.name, message, level)


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
