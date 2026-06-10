#!/usr/bin/env python3
"""Local web dashboard for node collection, validation, and database browsing."""

from __future__ import annotations

import json
import html
import hashlib
import secrets
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

from auth import (
    clear_cookie_header,
    cookie_header,
    cookie_token,
    create_session,
    ensure_default_admin,
    hash_password,
    token_hash,
    verify_password,
)
from app_config import CONFIG
from app_time import beijing_date, beijing_now
from app_version import APP_RELEASE_NAME, APP_VERSION
from bot_service import TelegramBot
from node_database import NodeDatabase
from node_collector import DEFAULT_REPOS
from node_processor import DEFAULT_RENAME_TEMPLATE, processed_nodes, subscription_base64, subscription_base64_from_rows
from node_validator import resolve_xray_path
from runtime_tasks import LogBus, ManagedTask
from subscription_filter import DEFAULT_SUBSCRIPTION_TARGET, MAX_SUBSCRIPTION_TARGET, final_subscription_nodes, normalize_subscription_limit
from services.acceptance_service import (
    acceptance_reports,
    build_acceptance_command,
    cleanup_acceptance_reports,
)
from services.converter_service import (
    SUB_STORE_INPUT_TYPES,
    SUB_STORE_PROJECT_URL,
    SUB_STORE_TARGETS,
    check_sub_store_health,
    convert_with_sub_store,
    sub_store_download_url,
    sub_store_unreachable_message,
    subscription_conversion_cache_identity,
    subscription_converter_input_types,
    subscription_converter_targets,
)
from services.maintenance_service import maintenance_overview_with_files
from services.system_health_service import system_health_summary
from services.xray_service import (
    activate_version,
    download_release,
    fetch_releases,
    local_versions,
    runtime_status as xray_runtime_status,
)


ROOT = CONFIG.root
DATABASE = CONFIG.database
WEB_ROOT = CONFIG.web_root
ADMIN_BASE_PATH = CONFIG.admin_base_path


LOG_BUS = LogBus(CONFIG.log_buffer_size, CONFIG.runtime_log)
TASKS: Dict[str, ManagedTask] = {
    "collector": ManagedTask("collector", LOG_BUS),
    "validator": ManagedTask("validator", LOG_BUS),
    "bot": ManagedTask("bot", LOG_BUS),
    "acceptance": ManagedTask("acceptance", LOG_BUS),
}


def privacy_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:32]


def stop_all_tasks(reason: str, wait: bool = False) -> None:
    LOG_BUS.emit("system", reason, "warning")
    stopped = []
    for task in TASKS.values():
        task.stop()
        stopped.append(task)
    if wait:
        for task in stopped:
            task.wait_stopped(CONFIG.task_stop_timeout)


def normalize_repo(value: str) -> str:
    value = value.strip()
    if not value or value.startswith("#"):
        return ""
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/")
    elif value.startswith("http://github.com/"):
        value = value.removeprefix("http://github.com/")
    value = value.strip("/").split("#", 1)[0].split("?", 1)[0]
    parts = [part for part in value.split("/") if part]
    if len(parts) < 2:
        return ""
    return parts[0] + "/" + parts[1]


def load_repo_config() -> List[str]:
    with NodeDatabase(DATABASE) as database:
        return database.collector_repos(DEFAULT_REPOS)


def save_repo_config(repos: List[str]) -> None:
    with NodeDatabase(DATABASE) as database:
        database.replace_collector_repos(repos)


def load_repo_items() -> List[dict]:
    with NodeDatabase(DATABASE) as database:
        return database.collector_repo_items(DEFAULT_REPOS)


def int_value(payload: dict, name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(payload.get(name, default))
    return max(minimum, min(value, maximum))


def float_value(payload: dict, name: str, default: float, minimum: float, maximum: float) -> float:
    value = float(payload.get(name, default))
    return max(minimum, min(value, maximum))


def log_level_value(value: object) -> str:
    level = str(value or "detail")
    return level if level in ("compact", "detail", "nodes") else "detail"


def normalize_datetime_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("T", " ")
    if len(text) == 16:
        text += ":00"
    datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return text


def datetime_is_expired(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S") <= beijing_now().replace(tzinfo=None)
    except ValueError:
        return True


def looks_like_replacement_garbage(value: object) -> bool:
    text = str(value or "").strip()
    if len(text) < 4 or "?" not in text:
        return False
    meaningful = [char for char in text if not char.isspace()]
    if not meaningful:
        return False
    question_marks = sum(1 for char in meaningful if char == "?")
    return question_marks / len(meaningful) >= 0.6



def build_collector_command(payload: dict) -> List[str]:
    delay = float_value(payload, "delay", 1.0, 0, 30)
    jitter = float_value(payload, "delay_jitter", 0.5, 0, 30)
    workers = int_value(payload, "workers", 5, 1, 12)
    max_depth = int_value(payload, "max_depth", 8, 0, 20)
    log_level = log_level_value(payload.get("log_level", "detail"))
    repos = load_repo_config()
    if not repos:
        raise ValueError("至少需要启用一个采集仓库")
    command = [
        sys.executable, "-u", "node_collector.py",
        "--database", str(DATABASE),
        "--shuffle-repos",
        "--delay", str(delay),
        "--delay-jitter", str(jitter),
        "--workers", str(workers),
        "--max-depth", str(max_depth),
        "--log-level", log_level,
    ]
    for repo in repos:
        command.extend(["--repo", repo])
    return command


def build_validator_command(payload: dict) -> List[str]:
    workers = int_value(payload, "workers", 10, 1, 50)
    limit = int_value(payload, "limit", 50, 1, 10000)
    rounds = int_value(payload, "rounds", 3, 1, 10)
    timeout = int_value(payload, "timeout", 8, 2, 60)
    command = [
        sys.executable, "-u", "node_validator.py",
        "--database", str(DATABASE),
        "--workers", str(workers),
        "--limit", str(limit),
        "--max-batch", str(limit),
        "--rounds", str(rounds),
        "--timeout", str(timeout),
    ]
    if payload.get("random"):
        command.append("--random")
    if payload.get("revalidate"):
        command.append("--revalidate")
    if payload.get("valid_only"):
        command.append("--valid-only")
    if payload.get("prefer_asia", True):
        command.append("--prefer-asia")
    return command


def build_bot_command() -> List[str]:
    return [sys.executable, "-u", "bot_service.py", "--database", str(DATABASE)]


def acceptance_status() -> dict:
    reports = acceptance_reports(ROOT, 10)
    return {
        "task": TASKS["acceptance"].status(),
        "latest": reports[0] if reports else None,
        "reports": reports,
    }


def bot_runtime_status(config: Optional[dict] = None) -> dict:
    if config is None:
        with NodeDatabase(DATABASE) as database:
            config = database.bot_config(mask_secrets=True)
    task = TASKS["bot"].status()
    if task["running"]:
        state = "运行中"
    elif not config.get("token_configured"):
        state = "配置不完整"
    elif config.get("auto_run"):
        state = "本次已停止，后台重启后自动恢复"
    else:
        state = "已停止"
    return {"task": task, "state": state, "auto_run": bool(config.get("auto_run"))}


def ensure_bot_auto_run() -> bool:
    with NodeDatabase(DATABASE) as database:
        config = database.bot_config()
    if not config["auto_run"]:
        return False
    if not config["bot_token"]:
        LOG_BUS.emit("bot", "BOT 宸茶缃嚜鍔ㄨ繍琛岋紝浣嗗皻鏈～鍐?Token", "warning")
        return False
    if task_is_running("bot"):
        return False
    changed = TASKS["bot"].start(build_bot_command())
    if changed:
        LOG_BUS.emit("bot", "宸叉牴鎹暟鎹簱閰嶇疆鑷姩鍚姩 BOT", "success")
    return changed


def task_is_running(name: str) -> bool:
    return bool(TASKS[name].status()["running"])


def active_worker_tasks() -> List[str]:
    return [name for name in ("collector", "validator") if task_is_running(name)]


def start_managed_task(name: str, command: List[str], source: str = "manual") -> tuple[bool, str]:
    other = "validator" if name == "collector" else "collector"
    if task_is_running(other):
        return False, "总控拒绝启动：验证运行时不能采集，采集运行时不能验证"
    if task_is_running(name):
        return False, "总控拒绝启动：任务已经在运行"
    changed = TASKS[name].start(command)
    if changed and source == "auto":
        LOG_BUS.emit("auto", ("总控已启动采集任务" if name == "collector" else "总控已启动验证任务"), "success")
    return changed, "ok"


class AutoController:
    def __init__(self, log_bus: LogBus):
        self.log_bus = log_bus
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.phase = "idle"
        self.mode = "idle"
        self.intent = "none"
        self.last_decision = "idle"
        self.last_reason = "自动控制尚未启动"
        self.collect_baseline = 0
        self.collect_target = 0
        self.validate_baseline = 0
        self.validate_target = 0
        self.started_at: Optional[float] = None
        self.last_recheck_at = 0.0
        self.last_maintenance_date = ""

    def start(self) -> None:
        with NodeDatabase(DATABASE) as database:
            database.update_auto_config({"enabled": True})
        with self.lock:
            self.mode = "auto"
            self.intent = "maintain_pool"
            self.last_decision = "checking"
            self.last_reason = "已开启自动控制，等待阈值检查"
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
        self.log_bus.emit("auto", "总控已开启自动运行", "success")

    def stop(self) -> None:
        with NodeDatabase(DATABASE) as database:
            database.update_auto_config({"enabled": False})
        with self.lock:
            self.phase = "stopping"
            self.mode = "stopping"
            self.intent = "stop_all"
            self.last_decision = "stop_requested"
            self.last_reason = "用户关闭自动控制，正在停止所有任务"
        TASKS["collector"].stop()
        TASKS["validator"].stop()
        self.log_bus.emit("auto", "总控已关闭自动运行，并请求停止采集和验证", "warning")

    def save_config(self, payload: dict) -> dict:
        cleaned = {
            "valid_low_watermark": int_value(payload, "valid_low_watermark", 1000, 0, 1000000),
            "collect_insert_target": int_value(payload, "collect_insert_target", 20000, 1, 1000000),
            "validate_valid_target": int_value(payload, "validate_valid_target", 200, 1, 1000000),
            "check_interval_minutes": int_value(payload, "check_interval_minutes", 5, 1, 1440),
            "collector_workers": int_value(payload, "collector_workers", 5, 1, 12),
            "collector_depth": int_value(payload, "collector_depth", 8, 0, 20),
            "collector_delay": float_value(payload, "collector_delay", 1.0, 0, 30),
            "collector_jitter": float_value(payload, "collector_jitter", 0.5, 0, 30),
            "collector_log_level": log_level_value(payload.get("collector_log_level", "detail")),
            "validator_workers": int_value(payload, "validator_workers", 20, 1, 50),
            "validator_rounds": int_value(payload, "validator_rounds", 1, 1, 10),
            "validator_timeout": int_value(payload, "validator_timeout", 5, 2, 60),
            "recheck_enabled": bool(payload.get("recheck_enabled")),
            "recheck_interval_minutes": int_value(payload, "recheck_interval_minutes", 360, 5, 1440),
            "recheck_limit": int_value(payload, "recheck_limit", 50, 1, 1000),
        }
        if "enabled" in payload:
            cleaned["enabled"] = bool(payload.get("enabled"))
        with NodeDatabase(DATABASE) as database:
            config = database.update_auto_config(cleaned)
        self.log_bus.emit("auto", "自动控制参数已保存到数据库", "success")
        return config

    def request_collect(self, payload: dict, source: str = "manual") -> tuple[bool, str]:
        repos = load_repo_config()
        if not repos:
            return False, "总控拒绝采集：至少需要启用一个采集仓库"
        if active_worker_tasks():
            return False, "总控拒绝采集：当前已有采集或验证任务运行"
        try:
            command = build_collector_command(payload)
        except ValueError as exc:
            return False, str(exc)
        with self.lock:
            self.mode = source
            self.intent = "collect"
            self.phase = "collecting"
            self.last_decision = "start_collector"
            self.collect_baseline = 0
            self.collect_target = int_value(payload, "target", 0, 0, 1000000)
            self.started_at = time.time()
            self.last_reason = "总控收到采集请求，已准备启动采集任务"
        self.log_bus.emit("auto", "总控接收采集请求，仓库数 " + str(len(repos)), "info")
        changed, reason = start_managed_task("collector", command, source)
        if changed:
            self._set("collecting", "总控已启动采集任务")
        else:
            self._set("idle", "采集未启动：" + reason)
        return changed, reason

    def request_validate(self, payload: dict, source: str = "manual") -> tuple[bool, str]:
        if active_worker_tasks():
            return False, "总控拒绝验证：当前已有采集或验证任务运行"
        with NodeDatabase(DATABASE) as database:
            stats = database.stats()
        pending_count = int(stats.get("pending_nodes", stats.get("total_nodes", 0)))
        valid_count = int(stats.get("valid_nodes", 0))
        if not payload.get("valid_only") and pending_count <= 0:
            return False, "总控拒绝验证：待验证节点池为空"
        command = build_validator_command(payload)
        with self.lock:
            self.mode = source
            self.intent = "recheck_valid" if payload.get("valid_only") else "validate_pending"
            self.phase = "rechecking" if payload.get("valid_only") else "validating"
            self.last_decision = "start_validator"
            self.validate_baseline = valid_count
            self.validate_target = int_value(payload, "target", 0, 0, 1000000)
            self.started_at = time.time()
            self.last_reason = "总控收到验证请求，已准备启动验证任务"
        changed, reason = start_managed_task("validator", command, source)
        if changed:
            self._set("rechecking" if payload.get("valid_only") else "validating", "总控已启动验证任务")
        else:
            self._set("idle", "验证未启动：" + reason)
        return changed, reason

    def stop_task(self, name: str) -> tuple[bool, str]:
        if name not in ("collector", "validator"):
            return False, "总控拒绝停止：未知任务"
        changed = TASKS[name].stop()
        with self.lock:
            self.mode = "manual"
            self.intent = "stop_" + name
            self.phase = "stopping_" + name
            self.last_decision = "stop_" + name
            self.last_reason = "总控已请求停止" + ("采集" if name == "collector" else "验证") + "任务"
        if changed:
            self.log_bus.emit("auto", self.last_reason, "warning")
        return changed, "ok" if changed else "任务未运行"

    def status(self) -> dict:
        with NodeDatabase(DATABASE) as database:
            config = database.auto_config()
            stats = database.stats()
        self._reconcile_completed_tasks(config)
        with self.lock:
            phase = self.phase
            mode = self.mode
            intent = self.intent
            last_decision = self.last_decision
            reason = self.last_reason
            started_at = self.started_at
            collect_baseline = self.collect_baseline
            collect_target = self.collect_target
            validate_baseline = self.validate_baseline
            validate_target = self.validate_target
        collector_progress = TASKS["collector"].status()["progress"]
        current_inserted = collector_progress.get("inserted_nodes", 0)
        valid_count = int(stats.get("valid_nodes", 0))
        validate_current = max(0, valid_count - validate_baseline) if validate_target else 0
        return {
            "enabled": bool(config["enabled"]),
            "mode": mode,
            "intent": intent,
            "phase": phase,
            "decision": last_decision,
            "last_reason": reason,
            "started_at": started_at,
            "running": {
                "collector": task_is_running("collector"),
                "validator": task_is_running("validator"),
                "bot": task_is_running("bot"),
                "active_workers": active_worker_tasks(),
            },
            "collect": {
                "baseline": collect_baseline,
                "target": collect_target,
                "current": current_inserted,
                "remaining": max(0, collect_target - current_inserted) if collect_target else 0,
            },
            "validate": {
                "baseline": validate_baseline,
                "target": validate_target,
                "current": validate_current,
                "remaining": max(0, validate_target - validate_current) if validate_target else 0,
            },
            "config": config,
        }

    def ensure_running(self) -> None:
        with NodeDatabase(DATABASE) as database:
            enabled = bool(database.auto_config()["enabled"])
        if enabled:
            self.start()

    def _loop(self) -> None:
        while True:
            with NodeDatabase(DATABASE) as database:
                config = database.auto_config()
                stats = database.stats()
            if not config["enabled"]:
                with self.lock:
                    if self.phase != "idle":
                        self.phase = "idle"
                        self.mode = "idle"
                        self.intent = "none"
                        self.last_decision = "disabled"
                        self.last_reason = "自动控制已关闭"
                return
            self._tick(config, stats)
            time.sleep(self._loop_sleep_seconds(config))

    def _loop_sleep_seconds(self, config: dict) -> int:
        with self.lock:
            active_phase = self.phase in (
                "collecting", "validating", "rechecking",
                "stopping", "stopping_collector", "stopping_validator",
            )
        if active_worker_tasks() or active_phase:
            return 5
        return int(config["check_interval_minutes"]) * 60

    def _reconcile_completed_tasks(self, config: dict) -> None:
        if active_worker_tasks():
            return
        with self.lock:
            if self.phase not in (
                "collecting", "validating", "rechecking",
                "stopping", "stopping_collector", "stopping_validator",
            ):
                return
            if config.get("enabled") and self.mode == "auto":
                self.last_decision = "worker_finished"
                self.last_reason = "任务已结束，等待总控下一轮决策"
                return
            self.phase = "idle"
            self.last_decision = "worker_finished"
            self.last_reason = "任务已结束，等待下一次总控指令"

    def _tick(self, config: dict, stats: dict) -> None:
        self._run_daily_maintenance_if_due()
        collector_running = task_is_running("collector")
        validator_running = task_is_running("validator")
        valid_count = int(stats.get("valid_nodes", 0))
        pending_count = int(stats.get("pending_nodes", stats.get("total_nodes", 0)))
        if collector_running and validator_running:
            TASKS["validator"].stop()
            with self.lock:
                self.mode = "auto"
                self.intent = "recover_conflict"
                self.last_decision = "stop_validator_conflict"
            self._set("error", "检测到采集和验证同时运行，已优先停止验证")
            return
        if collector_running:
            inserted = int(TASKS["collector"].status()["progress"].get("inserted_nodes", 0))
            target = int(config["collect_insert_target"])
            if inserted >= target:
                TASKS["collector"].stop()
                self._set("stopping_collector", "采集新增入库达到目标，正在停止采集并准备验证")
            else:
                self._set("collecting", "正在采集：新增入库 " + str(inserted) + "/" + str(target))
            return
        if validator_running:
            current = max(0, valid_count - self.validate_baseline)
            target = int(config["validate_valid_target"])
            if current >= target:
                TASKS["validator"].stop()
                self._set("stopping_validator", "本轮新增有效节点达到目标，正在停止验证")
            else:
                self._set("validating", "正在验证：本轮新增有效 " + str(current) + "/" + str(target))
            return
        if self.phase in ("collecting", "stopping_collector") and pending_count > 0:
            self._start_validator(config, valid_count, "采集阶段结束，节点库已有待验证节点，已自动启动验证")
            return
        if self.phase in ("validating", "stopping_validator"):
            current = max(0, valid_count - self.validate_baseline)
            if current >= int(config["validate_valid_target"]):
                self._set("idle", "本轮自动任务完成：有效节点已达到验证目标")
                return
            if pending_count > 0:
                self._start_validator(config, valid_count, "验证目标尚未达到，节点库仍有库存，继续自动验证下一批")
                return
            self._set("idle", "本轮自动任务结束：节点库暂无可验证节点")
            return
        if valid_count < int(config["valid_low_watermark"]):
            if pending_count > 0:
                self._start_validator(config, valid_count, "有效节点低于阈值，但节点库仍有待验证库存，优先启动验证")
                return
            self._start_collector(config, valid_count)
            return
        if self._should_recheck_valid_nodes(config):
            self._start_valid_recheck(config, valid_count, "已到达定时复检间隔，开始复检有效节点")
            return
        self._set("idle", "有效节点数量充足，等待下一次阈值检查")

    def _start_collector(self, config: dict, valid_count: int) -> None:
        payload = {
            "workers": config["collector_workers"],
            "max_depth": config["collector_depth"],
            "delay": config["collector_delay"],
            "delay_jitter": config["collector_jitter"],
            "log_level": config["collector_log_level"],
        }
        with self.lock:
            self.mode = "auto"
            self.intent = "collect_to_fill_pool"
            self.last_decision = "start_collector"
            self.collect_baseline = 0
            self.collect_target = int(config["collect_insert_target"])
            self.validate_baseline = valid_count
            self.validate_target = int(config["validate_valid_target"])
            self.started_at = time.time()
        try:
            command = build_collector_command(payload)
        except ValueError as exc:
            self._set("idle", "自动采集未启动：" + str(exc))
            return
        changed, reason = start_managed_task("collector", command, "auto")
        if changed:
            self._set("collecting", "有效节点低于阈值且节点库为空，已自动启动采集")
        else:
            self._set("idle", "自动采集未启动：" + reason)

    def _start_validator(self, config: dict, valid_count: int, reason_text: str) -> None:
        payload = {
            "workers": config["validator_workers"],
            "limit": self._auto_validator_limit(config),
            "rounds": config["validator_rounds"],
            "timeout": config["validator_timeout"],
        }
        with self.lock:
            self.mode = "auto"
            self.intent = "validate_pending"
            self.last_decision = "start_validator"
            if self.phase not in ("collecting", "stopping_collector", "validating", "stopping_validator"):
                self.validate_baseline = valid_count
                self.started_at = time.time()
            if self.validate_target == 0 or self.phase not in ("validating", "stopping_validator"):
                self.validate_target = int(config["validate_valid_target"])
        changed, reason = start_managed_task("validator", build_validator_command(payload), "auto")
        if changed:
            self._set("validating", reason_text)
        else:
            self._set("idle", "自动验证未启动：" + reason)

    def _auto_validator_limit(self, config: dict) -> int:
        target = int(config["validate_valid_target"])
        return min(1000, max(50, target * 5))

    def _should_recheck_valid_nodes(self, config: dict) -> bool:
        if not config.get("recheck_enabled"):
            return False
        interval = int(config.get("recheck_interval_minutes", 360)) * 60
        return time.time() - self.last_recheck_at >= interval

    def _start_valid_recheck(self, config: dict, valid_count: int, reason_text: str) -> None:
        payload = {
            "workers": config["validator_workers"],
            "limit": config["recheck_limit"],
            "rounds": config["validator_rounds"],
            "timeout": config["validator_timeout"],
            "valid_only": True,
            "prefer_asia": True,
        }
        with self.lock:
            self.mode = "auto"
            self.intent = "recheck_valid"
            self.last_decision = "start_valid_recheck"
            self.validate_baseline = valid_count
            self.validate_target = 0
            self.started_at = time.time()
            self.last_recheck_at = time.time()
        changed, reason = start_managed_task("validator", build_validator_command(payload), "auto")
        if changed:
            self._set("validating", reason_text)
        else:
            self._set("idle", "自动复检未启动：" + reason)

    def _set(self, phase: str, reason: str) -> None:
        should_emit = False
        with self.lock:
            if self.phase != phase or self.last_reason != reason:
                should_emit = True
            self.phase = phase
            self.last_reason = reason
        if should_emit:
            self.log_bus.emit("auto", reason, "info")

    def _run_daily_maintenance_if_due(self) -> None:
        now = beijing_now()
        today = now.strftime("%Y-%m-%d")
        if self.last_maintenance_date == today:
            return
        if active_worker_tasks():
            return
        with NodeDatabase(DATABASE) as database:
            config = database.maintenance_config()
            if not config["enabled"]:
                return
            if now.hour < int(config["schedule_hour"]):
                return
            if now.hour == int(config["schedule_hour"]) and now.minute < int(config["schedule_minute"]):
                return
            report_details = cleanup_acceptance_reports(ROOT, config)
            result = database.run_maintenance_cleanup("auto", config, report_details)
        self.last_maintenance_date = today
        self.log_bus.emit("maintenance", "系统维护已自动执行，清理 " + str(result["deleted_rows"]) + " 条记录", "success")


AUTO_CONTROLLER = AutoController(LOG_BUS)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "NodeDashboard/1.0"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/favicon.ico":
            return self.send_empty(HTTPStatus.NO_CONTENT)
        if parsed.path == "/healthz":
            return self.send_json(self.health_status())
        if parsed.path.startswith("/sub/"):
            return self.public_subscription(parsed.path)
        if parsed.path.startswith("/verify/"):
            return self.bot_verification_page(parsed.path)
        route = self.admin_route(parsed.path)
        if route is None:
            if parsed.path == "/":
                return self.redirect(ADMIN_BASE_PATH)
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        user = self.current_user()
        if route == "/login":
            if user:
                return self.redirect(ADMIN_BASE_PATH)
            return self.send_static("/login.html")
        if route == "/":
            if not user:
                return self.redirect(ADMIN_BASE_PATH + "/login")
            return self.send_static("/")
        if route.startswith("/api/") and route not in ("/api/login",):
            if not user:
                return self.send_json({"error": "璇峰厛鐧诲綍鍚庡彴"}, HTTPStatus.UNAUTHORIZED)
        if route == "/api/me":
            user = self.current_user()
            return self.send_json({"authenticated": bool(user), "user": user})
        if route == "/api/status":
            return self.send_json(self.dashboard_status())
        if route == "/api/ops-stats":
            query = urllib.parse.parse_qs(parsed.query)
            days = max(1, min(int(query.get("days", ["7"])[0]), 90))
            with NodeDatabase(DATABASE) as database:
                return self.send_json(database.ops_trend_stats(days))
        if route == "/api/runtime":
            return self.send_json(self.runtime_status())
        if route == "/api/xray/runtime":
            return self.send_json({"xray": xray_runtime_status(ROOT), "local": local_versions(ROOT)})
        if route == "/api/xray/releases":
            query = urllib.parse.parse_qs(parsed.query)
            system = query.get("platform", [""])[0].strip()
            arch = query.get("arch", [""])[0].strip()
            limit = max(1, min(int(query.get("limit", ["30"])[0]), 100))
            try:
                return self.send_json({"releases": fetch_releases(system, arch, limit)})
            except Exception as exc:
                return self.send_json({"error": "拉取 Xray 官方版本失败: " + str(exc)}, HTTPStatus.BAD_GATEWAY)
        if route == "/api/xray/local":
            return self.send_json({"local": local_versions(ROOT), "xray": xray_runtime_status(ROOT)})
        if route == "/api/auto":
            return self.send_json(AUTO_CONTROLLER.status())
        if route == "/api/repos":
            items = load_repo_items()
            repos = [item["repo"] for item in items if item["enabled"]]
            return self.send_json({"repos": repos, "items": items, "count": len(repos), "total": len(items)})
        if route == "/api/source-profiles":
            query = urllib.parse.parse_qs(parsed.query)
            limit = min(100, max(1, int(query.get("limit", ["20"])[0])))
            with NodeDatabase(DATABASE) as database:
                return self.send_json({"profiles": database.top_source_profiles(limit)})
        if route == "/api/subscriptions":
            with NodeDatabase(DATABASE) as database:
                return self.send_json({
                    "subscriptions": self.decorate_subscription_links(
                        database.subscription_links(),
                        database.claim_code_config(),
                    )
                })
        if route == "/api/publish-pool":
            with NodeDatabase(DATABASE) as database:
                return self.send_json(database.publish_pool_candidates())
        if route == "/api/subscription-converter/config":
            with NodeDatabase(DATABASE) as database:
                return self.send_json({
                    "config": database.subscription_converter_config(),
                    "targets": subscription_converter_targets(),
                    "input_types": subscription_converter_input_types(),
                    "logs": database.subscription_converter_logs(),
                    "project_url": SUB_STORE_PROJECT_URL,
                })
        if route == "/api/maintenance":
            with NodeDatabase(DATABASE) as database:
                return self.send_json(maintenance_overview_with_files(database, ROOT))
        if route == "/api/bot":
            with NodeDatabase(DATABASE) as database:
                config = database.bot_config(mask_secrets=True)
                return self.send_json({
                    "config": config,
                    "messages": database.bot_message_logs(),
                    **bot_runtime_status(config),
                })
        if route == "/api/acceptance":
            return self.send_json(acceptance_status())
        if route == "/api/claim-code/config":
            with NodeDatabase(DATABASE) as database:
                return self.send_json({"config": database.claim_code_config()})
        if route == "/api/valid-nodes":
            query = urllib.parse.parse_qs(parsed.query)
            page = max(1, int(query.get("page", ["1"])[0]))
            limit = min(100, max(1, int(query.get("limit", ["20"])[0])))
            protocol = query.get("protocol", [""])[0].strip().lower()
            country = query.get("country", [""])[0].strip().upper()
            with NodeDatabase(DATABASE) as database:
                return self.send_json({
                    "page": page,
                    "limit": limit,
                    "total": database.valid_node_count(protocol, country),
                    "protocols": database.valid_node_protocols(),
                    "countries": database.valid_node_countries(),
                    "nodes": database.valid_nodes(limit, (page - 1) * limit, protocol, country),
                })
        if route == "/api/node-processing/config":
            with NodeDatabase(DATABASE) as database:
                return self.send_json({"config": database.processing_config()})
        if route == "/api/node-processing/preview":
            query = urllib.parse.parse_qs(parsed.query)
            limit = min(100, max(1, int(query.get("limit", ["20"])[0])))
            with NodeDatabase(DATABASE) as database:
                config = database.processing_config()
                nodes = database.valid_nodes(limit, 0)
                rows = processed_nodes(nodes, config["rename_template"])
                return self.send_json({"template": config["rename_template"], "count": len(rows), "nodes": rows})
        if route == "/api/subscription/base64":
            return self.send_json({"error": "Base64 订阅已统一收口到订阅链接管理，请生成带 token 的订阅链接"}, HTTPStatus.GONE)
        if route == "/api/subscription/plain":
            return self.send_json({"error": "明文订阅已统一收口到订阅链接管理，请生成带 token 的订阅链接"}, HTTPStatus.GONE)
        if route == "/api/subscription/raw":
            with NodeDatabase(DATABASE) as database:
                nodes = database.export_valid_nodes(100, True)
            return self.send_text("\n".join(str(row["uri"]) for row in nodes) + "\n", "text/plain; charset=utf-8")
        if route == "/api/events":
            return self.send_events(parsed)
        return self.send_static(route)

    def do_POST(self) -> None:
        payload = self.read_json()
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/claim-code/redeem":
            return self.redeem_claim_code(payload)
        if parsed.path.startswith("/sub/"):
            return self.public_subscription_submit(parsed.path, payload)
        route = self.admin_route(parsed.path)
        if route is None:
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if route == "/api/login":
            return self.login(payload)
        user = self.current_user()
        if not user:
            return self.send_json({"error": "璇峰厛鐧诲綍鍚庡彴"}, HTTPStatus.UNAUTHORIZED)
        if route == "/api/logout":
            return self.logout()
        if route == "/api/account":
            return self.update_account(user, payload)
        if route == "/api/collector/start":
            changed, reason = AUTO_CONTROLLER.request_collect(payload)
            return self.task_response("collector", changed, reason)
        if route == "/api/collector/stop":
            changed, reason = AUTO_CONTROLLER.stop_task("collector")
            return self.task_response("collector", changed, reason)
        if route == "/api/validator/start":
            changed, reason = AUTO_CONTROLLER.request_validate(payload)
            return self.task_response("validator", changed, reason)
        if route == "/api/validator/recheck-valid":
            payload = dict(payload)
            payload["valid_only"] = True
            payload["prefer_asia"] = True
            changed, reason = AUTO_CONTROLLER.request_validate(payload)
            return self.task_response("validator", changed, reason)
        if route == "/api/validator/stop":
            changed, reason = AUTO_CONTROLLER.stop_task("validator")
            return self.task_response("validator", changed, reason)
        if route == "/api/bot/start":
            changed = TASKS["bot"].start(build_bot_command())
            return self.task_response("bot", changed, "ok" if changed else "BOT 鏈哄櫒浜哄凡缁忓湪杩愯")
        if route == "/api/bot/stop":
            return self.task_response("bot", TASKS["bot"].stop(), "ok")
        if route == "/api/bot/disable":
            with NodeDatabase(DATABASE) as database:
                config = database.update_bot_config({"auto_run": False})
            changed = TASKS["bot"].stop()
            LOG_BUS.emit("bot", "宸插叧闂?BOT 鑷姩杩愯锛屽苟璇锋眰鍋滄褰撳墠 BOT 浠诲姟", "warning")
            return self.send_json({"changed": changed, "config": config, **bot_runtime_status(config)})
        if route == "/api/bot/config":
            return self.update_bot_config(payload)
        if route == "/api/bot/simulate":
            return self.simulate_bot_message(payload)
        if route == "/api/bot/simulate-flow":
            return self.simulate_bot_flow(payload)
        if route == "/api/acceptance/start":
            return self.start_acceptance(payload)
        if route == "/api/acceptance/stop":
            return self.stop_acceptance()
        if route == "/api/claim-code/config":
            return self.update_claim_code_config(payload)
        if route == "/api/subscription-converter/config":
            return self.update_subscription_converter_config(payload)
        if route == "/api/subscription-converter/health":
            return self.check_subscription_converter_health(payload)
        if route == "/api/subscription-converter/convert":
            return self.convert_subscription(payload)
        if route == "/api/subscription-converter/cache/clear":
            return self.clear_subscription_converter_cache()
        if route == "/api/publish-pool/mark":
            return self.mark_publish_pool(payload)
        if route == "/api/publish-pool/remove":
            return self.remove_publish_pool(payload)
        if route == "/api/publish-pool/clear":
            return self.clear_publish_pool()
        if route == "/api/xray/download":
            return self.download_xray_release(payload)
        if route == "/api/xray/activate":
            return self.activate_xray_release(payload)
        if route == "/api/maintenance/config":
            return self.update_maintenance_config(payload)
        if route == "/api/maintenance/cleanup":
            return self.run_maintenance_cleanup()
        if route == "/api/auto/config":
            config = AUTO_CONTROLLER.save_config(payload)
            return self.send_json({"config": config, "auto": AUTO_CONTROLLER.status()})
        if route == "/api/auto/start":
            if payload:
                AUTO_CONTROLLER.save_config(payload)
            AUTO_CONTROLLER.start()
            return self.send_json({"auto": AUTO_CONTROLLER.status()})
        if route == "/api/auto/stop":
            AUTO_CONTROLLER.stop()
            return self.send_json({"auto": AUTO_CONTROLLER.status()})
        if route == "/api/node-processing/config":
            template = str(payload.get("rename_template", "")).strip() or DEFAULT_RENAME_TEMPLATE
            with NodeDatabase(DATABASE) as database:
                config = database.update_processing_config({"rename_template": template})
            return self.send_json({"config": config})
        if route == "/api/node-processing/preview":
            template = str(payload.get("rename_template", "")).strip()
            limit = int_value(payload, "limit", 20, 1, 100)
            with NodeDatabase(DATABASE) as database:
                if not template:
                    template = database.processing_config()["rename_template"]
                nodes = database.valid_nodes(limit, 0)
            rows = processed_nodes(nodes, template)
            return self.send_json({"template": template, "count": len(rows), "nodes": rows})
        if route == "/api/node-processing/export":
            return self.send_json({"error": "有效节点处理页不再生成订阅，请到订阅链接管理生成带 token 的订阅链接"}, HTTPStatus.GONE)
        if route == "/api/nodes/clear":
            return self.clear_node_pool(payload)
        if route == "/api/logs/clear":
            LOG_BUS.clear()
            return self.send_json({"cleared": True})
        if route == "/api/subscriptions":
            return self.create_subscription(payload)
        if route.startswith("/api/subscriptions/"):
            token = route.removeprefix("/api/subscriptions/").strip("/")
            if route.endswith("/test"):
                return self.test_subscription_format(token.removesuffix("/test").strip("/"), payload)
            if route.endswith("/disable"):
                return self.set_subscription_enabled(token.removesuffix("/disable").strip("/"), False)
            if route.endswith("/enable"):
                return self.set_subscription_enabled(token.removesuffix("/enable").strip("/"), True)
            if route.endswith("/delete"):
                return self.delete_subscription(token.removesuffix("/delete").strip("/"))
        if route.startswith("/api/repos/"):
            repo_action = route.removeprefix("/api/repos/").strip("/")
            if repo_action.endswith("/enable"):
                return self.set_repo_enabled(repo_action.removesuffix("/enable").strip("/"), True)
            if repo_action.endswith("/disable"):
                return self.set_repo_enabled(repo_action.removesuffix("/disable").strip("/"), False)
        if route == "/api/repos":
            raw_items = payload.get("repos", [])
            if isinstance(raw_items, str):
                raw_items = raw_items.splitlines()
            normalized = []
            seen = set()
            for item in raw_items if isinstance(raw_items, list) else []:
                repo = normalize_repo(str(item))
                if repo and repo not in seen:
                    normalized.append(repo)
                    seen.add(repo)
            if not normalized:
                return self.send_json({"error": "鑷冲皯闇€瑕佷竴涓湁鏁堜粨搴撳湴鍧€"}, HTTPStatus.BAD_REQUEST)
            save_repo_config(normalized)
            LOG_BUS.emit("collector", "浠撳簱鍒楄〃宸蹭繚瀛橈紝浠撳簱鏁?" + str(len(normalized)), "success")
            return self.send_json({"repos": normalized, "items": load_repo_items(), "count": len(normalized), "total": len(normalized)})
        if route == "/api/repos/reset":
            save_repo_config(list(DEFAULT_REPOS))
            LOG_BUS.emit("collector", "浠撳簱鍒楄〃宸叉仮澶嶉粯璁わ紝浠撳簱鏁?" + str(len(DEFAULT_REPOS)), "success")
            return self.send_json({"repos": list(DEFAULT_REPOS), "items": load_repo_items(), "count": len(DEFAULT_REPOS), "total": len(DEFAULT_REPOS)})
        return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def dashboard_status(self) -> dict:
        with NodeDatabase(DATABASE) as database:
            repos = database.collector_repos(DEFAULT_REPOS)
            control = AUTO_CONTROLLER.status()
            tasks = {name: task.status() for name, task in TASKS.items()}
            stats = database.stats()
            return {
                "app": {"version": APP_VERSION, "release": APP_RELEASE_NAME},
                "tasks": tasks,
                "auto": control,
                "control": control,
                "database": stats,
                "repos": {"items": repos, "count": len(repos)},
                "system_health": system_health_summary(stats, control, tasks),
            }

    def health_status(self) -> dict:
        control = AUTO_CONTROLLER.status()
        tasks = {name: task.status() for name, task in TASKS.items()}
        with NodeDatabase(DATABASE) as database:
            stats = database.stats()
        return {
            "ok": True,
            "app": {"version": APP_VERSION, "release": APP_RELEASE_NAME},
            "tasks": {name: status["running"] for name, status in tasks.items()},
            "control": control,
            "system_health": system_health_summary(stats, control, tasks),
        }

    def public_subscription(self, path: str) -> None:
        started = time.monotonic()
        token = path.removeprefix("/sub/").strip("/")
        if not token or "/" in token:
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        parsed = urllib.parse.urlsplit(getattr(self, "path", path))
        target_id = self.subscription_target_from_query(parsed.query)
        ip = self.client_ip()
        user_agent = self.headers.get("User-Agent", "")
        with NodeDatabase(DATABASE) as database:
            link = database.subscription_link(token)
            claim_config = database.claim_code_config()
            if not link:
                return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            available, status, reason = self.subscription_available(link, claim_config, enforce_claim_version=True)
            if not available:
                database.record_subscription_access(
                    beijing_date(),
                    token,
                    "expired",
                    privacy_hash(ip),
                    privacy_hash(user_agent),
                    0,
                    int((time.monotonic() - started) * 1000),
                    reason,
                )
                return self.send_json({"error": reason, "status": "expired"}, status)
            try:
                result = self.subscription_output(database, link, claim_config, target_id)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                message = "调用 Sub-Store 服务失败，" + sub_store_unreachable_message(database.subscription_converter_config().get("backend_url"), reason)
                return self.send_json({"error": message}, HTTPStatus.BAD_GATEWAY)
            except TimeoutError:
                return self.send_json({"error": "调用 Sub-Store 服务超时"}, HTTPStatus.GATEWAY_TIMEOUT)
            database.touch_subscription_link(token, ip)
            database.record_subscription_access(
                beijing_date(),
                token,
                "success",
                privacy_hash(ip),
                privacy_hash(user_agent),
                int(result["count"]),
                int((time.monotonic() - started) * 1000),
                "ok | " + str(result["target_id"]) + " | source=publish_pool | export_count=" + str(result["count"]),
                source="publish_pool",
                export_count=int(result["count"]),
            )
        LOG_BUS.emit("subscription", "订阅已访问 | " + str(link["name"]) + " | " + str(result["target_name"]) + " | 节点 " + str(result["count"]), "info")
        return self.send_text(str(result["content"]) + "\n", str(result["content_type"]))

    def public_subscription_submit(self, path: str, payload: dict) -> None:
        # Legacy compatibility path. The active product flow verifies claim codes in BOT,
        # then clients fetch /sub/{token}?target=... directly via GET.
        started = time.monotonic()
        token = path.removeprefix("/sub/").strip("/")
        if not token or "/" in token:
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        parsed = urllib.parse.urlsplit(getattr(self, "path", path))
        target_id = self.subscription_target_from_query(parsed.query, payload)
        code = str(payload.get("code", "")).strip()
        client_key = str(payload.get("client_id", "")).strip() or self.client_ip()
        client_key = client_key[:200] or "unknown"
        today = beijing_date()
        ip = self.client_ip()
        user_agent = self.headers.get("User-Agent", "")
        with NodeDatabase(DATABASE) as database:
            link = database.subscription_link(token)
            claim_config = database.claim_code_config()
            if not link:
                return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            available, status, reason = self.subscription_available(link, claim_config, enforce_claim_version=True)
            if not available:
                database.record_claim_attempt(today, client_key, str(link.get("claim_code_version") or ""), code, "expired", ip, user_agent)
                database.record_subscription_access(
                    today,
                    token,
                    "expired",
                    privacy_hash(ip),
                    privacy_hash(user_agent),
                    0,
                    int((time.monotonic() - started) * 1000),
                    reason,
                )
                return self.send_json({"error": reason, "status": "expired"}, status)
            verified, verify_status, message, http_status = self.verify_subscription_claim_code(database, claim_config, code, client_key, today, ip, user_agent)
            if not verified:
                database.record_subscription_access(
                    today,
                    token,
                    verify_status,
                    privacy_hash(ip),
                    privacy_hash(user_agent),
                    0,
                    int((time.monotonic() - started) * 1000),
                    message,
                )
                return self.send_json({"error": message, "status": verify_status}, http_status)
            try:
                result = self.subscription_output(database, link, claim_config, target_id)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                message = "调用 Sub-Store 服务失败，" + sub_store_unreachable_message(database.subscription_converter_config().get("backend_url"), reason)
                return self.send_json({"error": message}, HTTPStatus.BAD_GATEWAY)
            except TimeoutError:
                return self.send_json({"error": "调用 Sub-Store 服务超时"}, HTTPStatus.GATEWAY_TIMEOUT)
            database.touch_subscription_link(token, self.client_ip())
            database.record_subscription_access(
                today,
                token,
                "success",
                privacy_hash(ip),
                privacy_hash(user_agent),
                int(result["count"]),
                int((time.monotonic() - started) * 1000),
                "ok | " + str(result["target_id"]) + " | source=publish_pool | export_count=" + str(result["count"]),
                source="publish_pool",
                export_count=int(result["count"]),
            )
        LOG_BUS.emit("subscription", "订阅已访问 | " + str(link["name"]) + " | " + str(result["target_name"]) + " | 节点 " + str(result["count"]), "info")
        return self.send_text(str(result["content"]) + "\n", str(result["content_type"]))

    def verify_subscription_claim_code(
        self,
        database: NodeDatabase,
        config: dict,
        code: str,
        client_key: str,
        today: str,
        ip: str,
        user_agent: str,
    ) -> tuple[bool, str, str, HTTPStatus]:
        status, message, http_status = self.evaluate_claim_code(database, config, code, client_key, today)
        version = str(config["version"])
        database.record_claim_attempt(today, client_key, version, code, status, ip, user_agent)
        LOG_BUS.emit("claim", "璁㈤槄鍙ｄ护鏍￠獙 | " + status + " | " + client_key, "info")
        return status == "success", status, message, http_status

    def evaluate_claim_code(
        self,
        database: NodeDatabase,
        config: dict,
        code: str,
        client_key: str,
        today: str,
        version: Optional[str] = None,
    ) -> tuple[str, str, HTTPStatus]:
        current_version = str(config["version"])
        request_version = current_version if version is None else str(version)
        if not config["enabled"] or request_version != current_version:
            return "expired", str(config["expired_message"]), HTTPStatus.GONE
        if datetime_is_expired(config.get("expires_at")):
            return "expired", str(config["expired_message"]), HTTPStatus.GONE
        if code != str(config["code"]):
            return "wrong_code", str(config["wrong_code_message"]), HTTPStatus.BAD_REQUEST
        if database.claim_success_count(today, client_key, current_version) >= int(config["daily_limit"]):
            return "limit_exceeded", str(config["limit_exceeded_message"]), HTTPStatus.TOO_MANY_REQUESTS
        return "success", str(config["success_message"]), HTTPStatus.OK

    def subscription_target_from_query(self, query: str, payload: Optional[dict] = None) -> str:
        params = urllib.parse.parse_qs(query or "")
        raw = params.get("target", [""])[0] or params.get("format", [""])[0]
        if not raw and payload:
            raw = str(payload.get("target") or payload.get("format") or "")
        target = str(raw or "base64").strip().lower()
        aliases = {
            "": "base64",
            "default": "base64",
            "v2ray": "v2rayng",
            "v2rayn": "v2rayng",
            "clash": "clash-verge",
            "clashverge": "clash-verge",
            "mihomo": "clash-verge",
            "singbox": "sing-box",
            "shadowrocket": "shadowrocket",
            "raw": "raw",
            "plain": "raw",
            "base64": "base64",
        }
        return aliases.get(target, target)

    def subscription_output(self, database: NodeDatabase, link: dict, claim_config: dict, target_id: str) -> dict:
        config = database.processing_config()
        template = link["rename_template"] or config["rename_template"]
        limit = normalize_subscription_limit(link.get("export_limit") or DEFAULT_SUBSCRIPTION_TARGET)
        nodes = database.export_publish_subscription_nodes(limit)
        rows = processed_nodes(nodes, template)
        if target_id in ("base64", ""):
            result = subscription_base64_from_rows(rows)
            return {
                "target_id": "base64",
                "target_name": "通用 Base64",
                "content": result["subscription"],
                "content_type": "text/plain; charset=utf-8",
                "count": int(result["count"]),
                "source": "publish_pool",
            }
        if target_id == "raw":
            return {
                "target_id": "raw",
                "target_name": "原始节点",
                "content": "\n".join(str(row["uri"]) for row in rows),
                "content_type": "text/plain; charset=utf-8",
                "count": len(rows),
                "source": "publish_pool",
            }
        if target_id not in SUB_STORE_TARGETS:
            raise ValueError("不支持的订阅格式")
        converter_config = database.subscription_converter_config()
        converter_config["export_limit"] = limit
        converter_config["prefer_asia"] = True
        content = "\n".join(str(row["uri"]) for row in rows)
        input_mode = "subscription_link"
        input_type = "mixed"
        input_bytes = len(content.encode("utf-8"))
        target_name = SUB_STORE_TARGETS[target_id]["name"]
        claim_version = str(claim_config.get("version") or "")
        cache_meta = subscription_conversion_cache_identity(
            converter_config,
            target_id,
            content,
            input_mode,
            input_type,
            claim_version,
        )
        cached = database.subscription_conversion_cache_get(str(cache_meta["cache_key"]))
        if cached:
            self.record_converter_log(target_id, target_name, input_mode, input_type, len(nodes), input_bytes, int(cached.get("output_bytes") or 0), "success", "订阅链接缓存命中")
            return {
                "target_id": target_id,
                "target_name": target_name,
                "content": str(cached.get("content") or ""),
                "content_type": self.subscription_content_type(target_id),
                "count": len(nodes),
                "source": "publish_pool",
            }
        result = convert_with_sub_store(converter_config, target_id, content)
        output = str(result["content"])
        output_bytes = int(result["bytes"])
        database.subscription_conversion_cache_put({
            "cache_key": str(cache_meta["cache_key"]),
            "claim_code_version": claim_version,
            "target_id": target_id,
            "target_name": str(result["target"]),
            "node_hash": str(cache_meta["node_hash"]),
            "input_mode": input_mode,
            "input_type": input_type,
            "export_limit": limit,
            "prefer_asia": True,
            "backend_url": str(converter_config["backend_url"]),
            "profile_name": str(converter_config["profile_name"]),
            "content": output,
            "output_bytes": output_bytes,
        })
        self.record_converter_log(target_id, str(result["target"]), input_mode, input_type, len(nodes), input_bytes, output_bytes, "success", "订阅链接转换完成")
        return {
            "target_id": target_id,
            "target_name": str(result["target"]),
            "content": output,
            "content_type": self.subscription_content_type(target_id),
            "count": len(nodes),
            "source": "publish_pool",
        }

    def mark_publish_pool(self, payload: dict) -> None:
        uri = str(payload.get("uri") or "").strip()
        publishable = bool(payload.get("publishable", True))
        note = str(payload.get("note") or "").strip()
        if not uri:
            return self.send_json({"error": "缺少节点标识"}, HTTPStatus.BAD_REQUEST)
        try:
            with NodeDatabase(DATABASE) as database:
                row = database.mark_publish_node(uri, publishable, note)
                overview = database.publish_pool_candidates()
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        LOG_BUS.emit("subscription", "发布池人工标记 | " + ("可发布" if publishable else "不可发布") + " | " + str(row.get("name") or row.get("server") or "node"), "info")
        return self.send_json({"node": row, **overview})

    def remove_publish_pool(self, payload: dict) -> None:
        uri = str(payload.get("uri") or "").strip()
        if not uri:
            return self.send_json({"error": "缺少节点标识"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            removed = database.remove_publish_node(uri)
            overview = database.publish_pool_candidates()
        LOG_BUS.emit("subscription", "发布池移除节点 | removed=" + str(int(bool(removed))), "info")
        return self.send_json({"removed": bool(removed), **overview})

    def clear_publish_pool(self) -> None:
        with NodeDatabase(DATABASE) as database:
            removed = database.clear_publish_pool()
            overview = database.publish_pool_candidates()
        LOG_BUS.emit("subscription", "发布池已清空 | removed=" + str(removed), "warning")
        return self.send_json({"removed": removed, **overview})

    def subscription_content_type(self, target_id: str) -> str:
        if target_id == "sing-box":
            return "application/json; charset=utf-8"
        if target_id in ("clash-verge", "surge"):
            return "text/yaml; charset=utf-8"
        return "text/plain; charset=utf-8"

    def subscription_target_name(self, target_id: str) -> str:
        if target_id == "base64":
            return "通用 Base64"
        if target_id == "raw":
            return "原始节点"
        return str(SUB_STORE_TARGETS.get(target_id, {}).get("name") or target_id or "通用 Base64")

    def send_subscription_gate(
        self,
        link: dict,
        claim_config: dict,
        message: str = "",
        status: HTTPStatus = HTTPStatus.OK,
        target_id: str = "base64",
    ) -> None:
        version = str(link.get("claim_code_version") or "")
        current_version = str(claim_config.get("version") or "")
        disabled = status != HTTPStatus.OK
        target_name = self.subscription_target_name(target_id)
        safe_name = html.escape(str(link.get("name") or "订阅链接"))
        safe_message = html.escape(message or "请输入视频内领取口令，通过后才会生成真实订阅内容。")
        safe_target = html.escape(target_name)
        body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>订阅口令验证</title>
  <style>
    body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#070b12;color:#eef2f7;font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    main{{width:min(560px,calc(100% - 40px));padding:28px;border:1px solid #263548;border-radius:18px;background:#0c1420;box-shadow:0 30px 80px rgba(0,0,0,.45)}}
    h1{{margin:0 0 8px;color:#3dd6b5;font-size:28px}}p{{margin:8px 0;color:#b8c4d4}}label{{display:grid;gap:8px;margin-top:18px;color:#b8c4d4}}
    input{{min-height:46px;border:1px solid #2b3a50;border-radius:10px;background:#09101a;color:#eef2f7;padding:10px 12px;font:inherit}}
    button{{min-height:46px;margin-top:14px;border:0;border-radius:10px;background:#3dd6b5;color:#062923;padding:0 16px;font-weight:800;cursor:pointer}}
    button:disabled{{opacity:.45;cursor:not-allowed}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;border:1px solid #263548;border-radius:12px;padding:12px;background:#050910;color:#dce9f7}}
    .meta{{font-size:13px;color:#8391a5}}.error{{color:#ffb4bd}}
  </style>
</head>
<body>
  <main>
    <h1>订阅口令验证</h1>
    <p>{safe_name}</p>
    <p class="meta">输出格式：{safe_target}</p>
    <p class="{'error' if disabled else 'meta'}" id="message">{safe_message}</p>
    <p class="meta">链接绑定口令版本：{html.escape(version or "未绑定")}；当前口令版本：{html.escape(current_version)}</p>
    <label>领取口令验证码
      <input id="code" autocomplete="one-time-code" placeholder="输入视频内口令" {"disabled" if disabled else ""}>
    </label>
    <button id="submit" {"disabled" if disabled else ""}>验证并生成订阅</button>
    <pre id="output" hidden></pre>
  </main>
  <script>
    const button = document.getElementById("submit");
    const code = document.getElementById("code");
    const message = document.getElementById("message");
    const output = document.getElementById("output");
    button && button.addEventListener("click", async () => {{
      button.disabled = true;
      message.textContent = "正在验证口令...";
      output.hidden = true;
      try {{
        const response = await fetch(location.pathname + location.search, {{
          method: "POST",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify({{code: code.value, client_id: localStorage.getItem("huage_subscription_client") || ""}})
        }});
        const text = await response.text();
        if (!response.ok) {{
          try {{
            const payload = JSON.parse(text);
            message.textContent = payload.error || "验证失败";
          }} catch (error) {{
            message.textContent = text || "验证失败";
          }}
          button.disabled = false;
          return;
        }}
        message.textContent = "验证成功，下面是本次订阅内容。客户端导入时请使用新生成的有效链接。";
        output.textContent = text;
        output.hidden = false;
      }} catch (error) {{
        message.textContent = "请求失败：" + error.message;
        button.disabled = false;
      }}
    }});
  </script>
</body>
</html>"""
        return self.send_text(body, "text/html; charset=utf-8", status)

    def bot_verification_page(self, path: str) -> None:
        token = path.removeprefix("/verify/").strip("/")
        if not token or "/" in token:
            return self.send_json({"error": "验证链接不存在"}, HTTPStatus.NOT_FOUND)
        with NodeDatabase(DATABASE) as database:
            verification = database.bot_verification(token)
        if not verification:
            return self.send_json({"error": "验证链接不存在"}, HTTPStatus.NOT_FOUND)
        try:
            expires = datetime.strptime(str(verification["expires_at"]), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            expires = datetime.min
        if beijing_now().replace(tzinfo=None) >= expires:
            message = "验证链接已过期，请返回 BOT 重新获取。"
        else:
            message = "验证任务已建立。当前采用视频内口令轻量验证，不做 YouTube API 强制订阅校验。"
        body = (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>VMTOK 验证</title><style>"
            "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#000;color:#eef2f7;"
            "font:16px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
            "main{width:min(560px,calc(100% - 40px));padding:28px;border:1px solid #263548;border-radius:18px;"
            "background:#0c1420}h1{margin:0;color:#3dd6b5}p{color:#b8c4d4}</style></head>"
            "<body><main><h1>欢迎使用 VMTOK 验证系统</h1><p>" + message + "</p>"
            "<p>当前任务状态：" + str(verification["status"]) + "</p></main></body></html>"
        )
        return self.send_text(body, "text/html; charset=utf-8")

    def update_bot_config(self, payload: dict) -> None:
        allowed = {
            "bot_token", "bot_username", "keywords", "youtube_url", "youtube_channel_id",
            "auto_run", "group_prompt_message", "private_instruction_message",
            "subscription_card_message", "public_base_url", "verify_link_minutes",
            "subscription_max_uses", "subscription_expire_hours", "subscription_export_limit",
            "youtube_channel_url", "latest_free_node_video_url", "youtube_guide_message",
            "welcome_message", "unverified_message", "success_message", "youtube_url", "youtube_channel_id",
        }
        values = {key: payload[key] for key in allowed if key in payload}
        token = str(values.get("bot_token", "")).strip()
        if token and "..." in token:
            values.pop("bot_token", None)
        with NodeDatabase(DATABASE) as database:
            config = database.update_bot_config(values)
        ensure_bot_auto_run()
        LOG_BUS.emit("bot", "BOT 配置已保存到数据库", "success")
        return self.send_json({"config": config, **bot_runtime_status(config)})

    def simulate_bot_message(self, payload: dict) -> None:
        text = str(payload.get("text", "")).strip()
        chat_type = str(payload.get("chat_type", "group")).strip() or "group"
        if chat_type not in ("group", "supergroup", "private"):
            return self.send_json({"error": "浼氳瘽绫诲瀷鍙兘鏄兢缁勬垨绉佽亰"}, HTTPStatus.BAD_REQUEST)
        chat_id = str(payload.get("chat_id", "")).strip() or ("-100001" if chat_type in ("group", "supergroup") else "200001")
        user_id = str(payload.get("user_id", "")).strip() or "200001"
        username = str(payload.get("username", "")).strip() or "sim_user"
        if not text:
            return self.send_json({"error": "妯℃嫙娑堟伅鍐呭涓嶈兘涓虹┖"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            config = database.bot_config()
        result = TelegramBot(DATABASE).handle_message(
            str(config.get("bot_token") or "simulate-token"),
            config,
            text,
            chat_id,
            chat_type,
            user_id,
            username,
            simulate=True,
        )
        LOG_BUS.emit(
            "bot",
            "BOT 妯℃嫙楠岃瘉 | " + str(result.get("action")) + " | " + str(result.get("status")) + " | 鐢ㄦ埛 " + user_id,
            "success" if result.get("status") in ("sent", "success") else "warning",
        )
        with NodeDatabase(DATABASE) as database:
            messages = database.bot_message_logs()
        return self.send_json({"result": result, "messages": messages})

    def simulate_bot_flow(self, payload: dict) -> None:
        user_id = str(payload.get("user_id", "")).strip() or ("flow_" + secrets.token_hex(6))
        username = str(payload.get("username", "")).strip() or user_id
        group_chat_id = str(payload.get("group_chat_id", "")).strip() or "-100001"
        steps = []
        generated_token = ""
        cleanup_deleted = False
        with NodeDatabase(DATABASE) as database:
            bot_config = database.bot_config()
            claim_config = database.claim_code_config()
        keyword = str(payload.get("keyword", "")).strip()
        if not keyword:
            keyword = next((item.strip() for item in str(bot_config.get("keywords") or "").replace(",", "\n").splitlines() if item.strip()), "")
        code = str(payload.get("code", "")).strip() or str(claim_config.get("code") or "")
        bot = TelegramBot(DATABASE)

        def add_step(name: str, ok: bool, detail: str, data: Optional[dict] = None) -> None:
            steps.append({"name": name, "ok": bool(ok), "detail": detail, "data": data or {}})

        try:
            if not keyword:
                add_step("群组关键词", False, "BOT 关键词为空，无法模拟群组触发")
            else:
                group_result = bot.handle_message(
                    str(bot_config.get("bot_token") or "simulate-token"),
                    bot_config,
                    keyword,
                    group_chat_id,
                    "group",
                    user_id,
                    username,
                    simulate=True,
                )
                group_reply = (group_result.get("replies") or [{}])[0]
                has_button = bool(group_reply.get("reply_markup"))
                add_step(
                    "群组关键词",
                    group_result.get("action") == "group_prompt" and group_result.get("status") == "sent",
                    "群组命中关键词并发送私聊按钮" if has_button else "群组命中关键词并发送提示；未生成按钮，请检查 BOT 用户名",
                    {"result": group_result, "has_button": has_button},
                )

            private_result = bot.handle_message(
                str(bot_config.get("bot_token") or "simulate-token"),
                bot_config,
                "/start claim",
                user_id,
                "private",
                user_id,
                username,
                simulate=True,
            )
            add_step(
                "私聊入口",
                private_result.get("action") == "private_instruction" and private_result.get("status") == "sent",
                "点击按钮后 /start claim 已触发领取说明",
                {"result": private_result},
            )

            claim_result = bot.handle_message(
                str(bot_config.get("bot_token") or "simulate-token"),
                bot_config,
                code,
                user_id,
                "private",
                user_id,
                username,
                simulate=True,
            )
            subscription = claim_result.get("subscription") or {}
            generated_token = str(subscription.get("token") or "")
            add_step(
                "口令领取",
                claim_result.get("status") == "success" and bool(generated_token),
                "口令验证成功并生成订阅" if generated_token else str(claim_result.get("reason") or "未生成订阅"),
                {"result": claim_result},
            )

            version_ok = bool(generated_token) and str(subscription.get("claim_code_version") or "") == str(claim_config.get("version") or "")
            add_step(
                "版本绑定",
                version_ok,
                "订阅绑定当前口令版本" if version_ok else "订阅口令版本不一致",
                {"subscription_version": subscription.get("claim_code_version"), "current_version": claim_config.get("version")},
            )

            if generated_token:
                with NodeDatabase(DATABASE) as database:
                    link = database.subscription_link(generated_token)
                    current_claim = database.claim_code_config()
                    available, status, reason = self.subscription_available(link or {}, current_claim, enforce_claim_version=True)
                add_step(
                    "订阅入口安全",
                    bool(link) and available,
                    "订阅入口会先显示验证码窗口，不直接导出真实节点" if available else reason,
                    {"status_code": int(status), "reason": reason},
                )
            else:
                add_step("订阅入口安全", False, "没有生成订阅，无法检查入口")
        finally:
            if generated_token:
                with NodeDatabase(DATABASE) as database:
                    cleanup_deleted = database.delete_subscription_link(generated_token)
                add_step(
                    "清理测试订阅",
                    cleanup_deleted,
                    "测试订阅已删除" if cleanup_deleted else "测试订阅清理失败",
                    {"token": generated_token},
                )

        ok = all(step["ok"] for step in steps)
        with NodeDatabase(DATABASE) as database:
            messages = database.bot_message_logs()
        LOG_BUS.emit("bot", "BOT 完整流程模拟 | " + ("通过" if ok else "失败") + " | 用户 " + user_id, "success" if ok else "warning")
        return self.send_json({
            "ok": ok,
            "user_id": user_id,
            "keyword": keyword,
            "claim_version": str(claim_config.get("version") or ""),
            "generated_token": generated_token,
            "cleanup_deleted": cleanup_deleted,
            "steps": steps,
            "messages": messages,
        })

    def start_acceptance(self, payload: dict) -> None:
        if TASKS["acceptance"].status()["running"]:
            return self.send_json({"changed": False, "status": acceptance_status(), "reason": "验收任务已经在运行"})
        cleanup_details = {}
        with NodeDatabase(DATABASE) as database:
            cleanup_details = cleanup_acceptance_reports(ROOT, database.maintenance_config())
        if cleanup_details.get("acceptance_reports_deleted"):
            LOG_BUS.emit(
                "maintenance",
                "真实验收启动前已清理报告 "
                + str(cleanup_details["acceptance_reports_deleted"])
                + " 个文件",
                "success",
            )
        command = build_acceptance_command(payload, ADMIN_BASE_PATH)
        changed = TASKS["acceptance"].start(command)
        LOG_BUS.emit("acceptance", "真实验收已启动，调用现有后台链路执行", "success" if changed else "warning")
        return self.send_json({
            "changed": changed,
            "status": acceptance_status(),
            "command": command,
            "cleanup": cleanup_details,
        })

    def stop_acceptance(self) -> None:
        changed = TASKS["acceptance"].stop()
        LOG_BUS.emit("acceptance", "已请求停止真实验收任务", "warning")
        return self.send_json({"changed": changed, "status": acceptance_status()})

    def update_claim_code_config(self, payload: dict) -> None:
        allowed = {
            "enabled", "code", "version", "expires_at", "daily_limit", "success_message",
            "wrong_code_message", "expired_message", "limit_exceeded_message",
        }
        values = {key: payload[key] for key in allowed if key in payload}
        if "code" in values and not str(values["code"]).strip():
            return self.send_json({"error": "领取口令不能为空"}, HTTPStatus.BAD_REQUEST)
        if "version" in values and not str(values["version"]).strip():
            return self.send_json({"error": "口令版本不能为空"}, HTTPStatus.BAD_REQUEST)
        for key in ("success_message", "wrong_code_message", "expired_message", "limit_exceeded_message"):
            if key in values and looks_like_replacement_garbage(values[key]):
                return self.send_json({"error": "口令提示文案疑似编码损坏，请重新输入中文后保存"}, HTTPStatus.BAD_REQUEST)
        if "expires_at" in values:
            try:
                values["expires_at"] = normalize_datetime_value(values["expires_at"])
            except ValueError:
                return self.send_json({"error": "口令有效期格式不正确"}, HTTPStatus.BAD_REQUEST)
        try:
            with NodeDatabase(DATABASE) as database:
                config = database.update_claim_code_config(values)
        except (TypeError, ValueError):
            return self.send_json({"error": "每日领取次数必须是有效数字"}, HTTPStatus.BAD_REQUEST)
        LOG_BUS.emit("claim", "领取口令配置已保存，当前版本 " + str(config["version"]), "success")
        return self.send_json({"config": config})

    def update_subscription_converter_config(self, payload: dict) -> None:
        allowed = {"backend_url", "profile_name", "export_limit", "prefer_asia"}
        values = {key: payload[key] for key in allowed if key in payload}
        if "backend_url" in values:
            backend_url = str(values["backend_url"]).strip()
            if backend_url and not backend_url.startswith(("http://", "https://")):
                return self.send_json({"error": "Sub-Store 服务地址必须以 http:// 或 https:// 开头"}, HTTPStatus.BAD_REQUEST)
        try:
            with NodeDatabase(DATABASE) as database:
                config = database.update_subscription_converter_config(values)
        except (TypeError, ValueError):
            return self.send_json({"error": "订阅转换配置包含无效数值"}, HTTPStatus.BAD_REQUEST)
        try:
            sub_store_download_url(config, "v2rayng", "vless://example")
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        LOG_BUS.emit("processor", "订阅转换配置已保存 | " + str(config["backend_url"]), "success")
        with NodeDatabase(DATABASE) as database:
            logs = database.subscription_converter_logs()
        return self.send_json({
            "config": config,
            "targets": subscription_converter_targets(),
            "input_types": subscription_converter_input_types(),
            "logs": logs,
            "project_url": SUB_STORE_PROJECT_URL,
        })

    def check_subscription_converter_health(self, payload: dict) -> None:
        with NodeDatabase(DATABASE) as database:
            config = database.subscription_converter_config()
        if "backend_url" in payload:
            backend_url = str(payload.get("backend_url", "")).strip()
            if backend_url:
                config["backend_url"] = backend_url
        try:
            health = check_sub_store_health(config)
            status = "success" if health["ok"] else "failed"
            message = health["message"]
        except ValueError as exc:
            health = {
                "ok": False,
                "backend_url": str(config.get("backend_url") or ""),
                "status_code": 0,
                "message": str(exc),
                "latency_ms": 0,
            }
            status = "failed"
            message = str(exc)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            message = sub_store_unreachable_message(config.get("backend_url"), reason)
            health = {
                "ok": False,
                "backend_url": str(config.get("backend_url") or ""),
                "status_code": 0,
                "message": message,
                "latency_ms": 0,
            }
            status = "failed"
            message = str(health["message"])
        except TimeoutError:
            message = "Sub-Store 服务健康检查超时；当前地址 " + str(config.get("backend_url") or "未配置")
            health = {
                "ok": False,
                "backend_url": str(config.get("backend_url") or ""),
                "status_code": 0,
                "message": message,
                "latency_ms": 0,
            }
            status = "failed"
            message = str(health["message"])
        self.record_converter_log(
            "health",
            "Sub-Store Health",
            "health",
            "health",
            0,
            0,
            0,
            status,
            message,
        )
        with NodeDatabase(DATABASE) as database:
            logs = database.subscription_converter_logs()
        LOG_BUS.emit("processor", "Sub-Store 健康检查 | " + message, "success" if status == "success" else "warning")
        return self.send_json({"health": health, "logs": logs})

    def convert_subscription(self, payload: dict) -> None:
        target_id = str(payload.get("target", "")).strip()
        input_mode = str(payload.get("input_mode", "valid_nodes")).strip() or "valid_nodes"
        input_type = str(payload.get("input_type", "auto")).strip().lower() or "auto"
        if input_type not in SUB_STORE_INPUT_TYPES:
            return self.send_json({"error": "不支持的输入协议类型"}, HTTPStatus.BAD_REQUEST)
        target_name = SUB_STORE_TARGETS.get(target_id, {}).get("name", target_id or "unknown")
        with NodeDatabase(DATABASE) as database:
            config = database.subscription_converter_config()
            claim_config = database.claim_code_config()
            if "backend_url" in payload:
                backend_url = str(payload.get("backend_url") or "").strip()
                if backend_url:
                    config["backend_url"] = backend_url
            if "profile_name" in payload:
                profile_name = str(payload.get("profile_name") or "").strip().strip("/")
                if profile_name:
                    config["profile_name"] = profile_name
            if "prefer_asia" in payload:
                config["prefer_asia"] = payload.get("prefer_asia") is True or str(payload.get("prefer_asia")).lower() in ("1", "true", "yes", "on")
            if "export_limit" in payload:
                try:
                    config["export_limit"] = int_value(payload, "export_limit", int(config["export_limit"]), 1, MAX_SUBSCRIPTION_TARGET)
                except (TypeError, ValueError):
                    return self.send_json({"error": "导出数量必须是有效数字"}, HTTPStatus.BAD_REQUEST)
            if input_mode == "custom":
                content = str(payload.get("content", "")).strip()
                node_count = len([line for line in content.splitlines() if line.strip()])
            else:
                template = database.processing_config()["rename_template"]
                nodes = final_subscription_nodes(
                    database.export_subscription_nodes(int(config["export_limit"]), bool(config["prefer_asia"])),
                    int(config["export_limit"]),
                )
                rows = processed_nodes(nodes, template)
                content = "\n".join(str(row["uri"]) for row in rows)
                node_count = len(rows)
        input_bytes = len(content.encode("utf-8"))
        claim_version = str(claim_config.get("version") or "")
        cache_meta = subscription_conversion_cache_identity(config, target_id, content, input_mode, input_type, claim_version)
        if target_id in SUB_STORE_TARGETS:
            with NodeDatabase(DATABASE) as database:
                cached = database.subscription_conversion_cache_get(str(cache_meta["cache_key"]))
            if cached:
                result = {
                    "target": target_name,
                    "target_id": target_id,
                    "sub_store_target": SUB_STORE_TARGETS[target_id]["target"],
                    "content": str(cached.get("content") or ""),
                    "bytes": int(cached.get("output_bytes") or 0),
                    "source": "Sub-Store cache",
                    "project_url": SUB_STORE_PROJECT_URL,
                }
                self.record_converter_log(target_id, target_name, input_mode, input_type, node_count, input_bytes, int(result["bytes"]), "success", "缓存命中")
                LOG_BUS.emit("processor", "订阅转换缓存命中 | " + target_name + " | 节点 " + str(node_count), "success")
                with NodeDatabase(DATABASE) as database:
                    logs = database.subscription_converter_logs()
                    cache_stats = database.subscription_conversion_cache_stats()
                return self.send_json({
                    **result,
                    "node_count": node_count,
                    "input_mode": input_mode,
                    "input_type": input_type,
                    "logs": logs,
                    "cache": {"hit": True, "key": str(cache_meta["cache_key"]), "stats": cache_stats},
                    "config": {
                        "backend_url": config["backend_url"],
                        "profile_name": config["profile_name"],
                        "export_limit": int(config["export_limit"]),
                        "prefer_asia": bool(config["prefer_asia"]),
                    },
                })
        try:
            result = convert_with_sub_store(config, target_id, content)
        except ValueError as exc:
            self.record_converter_log(target_id, target_name, input_mode, input_type, node_count, input_bytes, 0, "failed", str(exc))
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            message = "调用 Sub-Store 服务失败，" + sub_store_unreachable_message(config.get("backend_url"), reason)
            self.record_converter_log(target_id, target_name, input_mode, input_type, node_count, input_bytes, 0, "failed", message)
            return self.send_json({"error": message}, HTTPStatus.BAD_GATEWAY)
        except TimeoutError:
            message = "调用 Sub-Store 服务超时；当前地址 " + str(config.get("backend_url") or "未配置")
            self.record_converter_log(target_id, target_name, input_mode, input_type, node_count, input_bytes, 0, "failed", message)
            return self.send_json({"error": message}, HTTPStatus.GATEWAY_TIMEOUT)
        except Exception as exc:
            message = "订阅转换失败: " + str(exc)
            self.record_converter_log(target_id, target_name, input_mode, input_type, node_count, input_bytes, 0, "failed", message)
            return self.send_json({"error": message}, HTTPStatus.BAD_GATEWAY)
        self.record_converter_log(target_id, str(result["target"]), input_mode, input_type, node_count, input_bytes, int(result["bytes"]), "success", "转换完成")
        LOG_BUS.emit("processor", "订阅转换完成 | " + str(result["target"]) + " | 节点 " + str(node_count), "success")
        with NodeDatabase(DATABASE) as database:
            database.subscription_conversion_cache_put({
                "cache_key": str(cache_meta["cache_key"]),
                "claim_code_version": claim_version,
                "target_id": target_id,
                "target_name": str(result["target"]),
                "node_hash": str(cache_meta["node_hash"]),
                "input_mode": input_mode,
                "input_type": input_type,
                "export_limit": int(config["export_limit"]),
                "prefer_asia": bool(config["prefer_asia"]),
                "backend_url": str(config["backend_url"]),
                "profile_name": str(config["profile_name"]),
                "content": str(result["content"]),
                "output_bytes": int(result["bytes"]),
            })
            logs = database.subscription_converter_logs()
            cache_stats = database.subscription_conversion_cache_stats()
        return self.send_json({
            **result,
            "node_count": node_count,
            "input_mode": input_mode,
            "input_type": input_type,
            "logs": logs,
            "cache": {"hit": False, "key": str(cache_meta["cache_key"]), "stats": cache_stats},
            "config": {
                "backend_url": config["backend_url"],
                "profile_name": config["profile_name"],
                "export_limit": int(config["export_limit"]),
                "prefer_asia": bool(config["prefer_asia"]),
            },
        })

    def update_maintenance_config(self, payload: dict) -> None:
        allowed = {
            "enabled", "schedule_hour", "schedule_minute",
            "converter_log_days", "converter_log_max_rows",
            "bot_log_days", "bot_log_max_rows",
            "claim_record_days", "subscription_access_days",
            "subscription_access_max_rows", "maintenance_record_days",
            "stale_unvalidated_node_days", "invalid_node_days", "bot_verification_days",
            "conversion_cache_days", "conversion_cache_max_rows",
            "daily_stats_days", "acceptance_report_days",
            "acceptance_failed_report_days", "acceptance_report_max_files",
            "vacuum_after_cleanup",
        }
        values = {key: payload[key] for key in allowed if key in payload}
        try:
            with NodeDatabase(DATABASE) as database:
                config = database.update_maintenance_config(values)
                overview = maintenance_overview_with_files(database, ROOT)
        except (TypeError, ValueError):
            return self.send_json({"error": "系统维护配置包含无效数值"}, HTTPStatus.BAD_REQUEST)
        LOG_BUS.emit("maintenance", "系统维护配置已保存", "success")
        overview["config"] = config
        return self.send_json(overview)

    def run_maintenance_cleanup(self) -> None:
        with NodeDatabase(DATABASE) as database:
            config = database.maintenance_config()
            report_details = cleanup_acceptance_reports(ROOT, config)
            result = database.run_maintenance_cleanup("manual", config, report_details)
            overview = maintenance_overview_with_files(database, ROOT)
        LOG_BUS.emit("maintenance", "系统维护已手动执行，清理 " + str(result["deleted_rows"]) + " 条记录", "success")
        overview["result"] = result
        return self.send_json(overview)

    def clear_subscription_converter_cache(self) -> None:
        with NodeDatabase(DATABASE) as database:
            deleted = database.clear_subscription_conversion_cache()
            overview = maintenance_overview_with_files(database, ROOT)
        LOG_BUS.emit("processor", "订阅转换缓存已手动清空，删除 " + str(deleted) + " 条", "warning")
        return self.send_json({"deleted": deleted, "maintenance": overview})

    def clear_node_pool(self, payload: dict) -> None:
        if active_worker_tasks():
            return self.send_json({"error": "采集或验证任务运行中，不能清空节点池"}, HTTPStatus.CONFLICT)
        scope = str(payload.get("scope", "")).strip().lower()
        confirm = str(payload.get("confirm", "")).strip()
        labels = {"pending": "清空未验证节点", "valid": "清空有效节点"}
        if scope not in labels:
            return self.send_json({"error": "清理范围不正确"}, HTTPStatus.BAD_REQUEST)
        if confirm != labels[scope]:
            return self.send_json({"error": "确认文本不正确"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            details = database.clear_node_pool(scope)
            stats = database.stats()
        LOG_BUS.emit("maintenance", labels[scope] + " | " + str(details), "warning")
        return self.send_json({"cleared": True, "scope": scope, "details": details, "database": stats})

    def download_xray_release(self, payload: dict) -> None:
        version = str(payload.get("version", "")).strip()
        asset_url = str(payload.get("asset_url", "")).strip()
        asset_name = str(payload.get("asset_name", "")).strip() or Path(asset_url).name
        try:
            result = download_release(ROOT, version, asset_url, asset_name)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        LOG_BUS.emit("validator", "Xray 版本已下载 | " + str(result["version"]), "success")
        return self.send_json({"download": result, "local": local_versions(ROOT)})

    def activate_xray_release(self, payload: dict) -> None:
        if TASKS["validator"].status().get("running"):
            return self.send_json({"error": "验证任务运行中，不能切换 Xray 内核"}, HTTPStatus.CONFLICT)
        version = str(payload.get("version", "")).strip()
        try:
            result = activate_version(ROOT, version)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        LOG_BUS.emit("validator", "Xray 当前版本已切换 | " + str(result["version"]), "warning")
        return self.send_json({"activated": result, "xray": xray_runtime_status(ROOT), "local": local_versions(ROOT)})

    def record_converter_log(
        self,
        target_id: str,
        target_name: str,
        input_mode: str,
        input_type: str,
        node_count: int,
        input_bytes: int,
        output_bytes: int,
        status: str,
        message: str,
    ) -> None:
        with NodeDatabase(DATABASE) as database:
            database.record_subscription_converter_log(
                target_id,
                target_name,
                input_mode,
                input_type,
                node_count,
                input_bytes,
                output_bytes,
                status,
                message,
            )

    def redeem_claim_code(self, payload: dict) -> None:
        code = str(payload.get("code", "")).strip()
        version = str(payload.get("version", "")).strip()
        client_key = str(payload.get("client_id", "")).strip() or self.client_ip()
        client_key = client_key[:200] or "unknown"
        today = beijing_date()
        ip = self.client_ip()
        user_agent = self.headers.get("User-Agent", "")
        with NodeDatabase(DATABASE) as database:
            config = database.claim_code_config()
            status, message, http_status = self.evaluate_claim_code(database, config, code, client_key, today, version)
            database.record_claim_attempt(today, client_key, version, code, status, ip, user_agent)
        LOG_BUS.emit("claim", "棰嗗彇鍙ｄ护鏍￠獙 | " + status + " | " + client_key, "info")
        return self.send_json({
            "ok": status == "success",
            "status": status,
            "message": message,
            "version": str(config["version"]),
            "date": today,
        }, http_status)

    def subscription_available(
        self,
        link: dict,
        claim_config: Optional[dict] = None,
        enforce_claim_version: bool = False,
    ) -> tuple[bool, HTTPStatus, str]:
        if not link["enabled"]:
            return False, HTTPStatus.FORBIDDEN, "订阅链接已禁用"
        if enforce_claim_version:
            if not claim_config or not claim_config.get("enabled"):
                return False, HTTPStatus.GONE, str((claim_config or {}).get("expired_message") or "口令已过期，请获取最新口令后再试。")
            link_version = str(link.get("claim_code_version") or "")
            current_version = str(claim_config.get("version") or "")
            if not link_version or link_version != current_version:
                return False, HTTPStatus.GONE, str(claim_config.get("expired_message") or "口令已更新，请重新领取最新订阅链接。")
        if link["mode"] in ("usage", "either"):
            max_uses = int(link["max_uses"] or 0)
            if max_uses <= 0 or int(link["used_count"] or 0) >= max_uses:
                return False, HTTPStatus.GONE, "订阅链接使用次数已用完"
        if link["mode"] in ("time", "either"):
            expires_at = str(link.get("expires_at") or "")
            if not expires_at:
                return False, HTTPStatus.GONE, "订阅链接缺少过期时间"
            try:
                expires = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return False, HTTPStatus.GONE, "订阅链接过期时间格式错误"
            if beijing_now().replace(tzinfo=None) >= expires:
                return False, HTTPStatus.GONE, "订阅链接已过期"
        return True, HTTPStatus.OK, "ok"

    def create_subscription(self, payload: dict) -> None:
        name = str(payload.get("name", "")).strip() or "临时订阅"
        mode = str(payload.get("mode", "usage")).strip()
        template = str(payload.get("rename_template", "")).strip()
        remark = str(payload.get("remark", "")).strip()
        export_limit = int_value(payload, "export_limit", DEFAULT_SUBSCRIPTION_TARGET, 1, MAX_SUBSCRIPTION_TARGET)
        max_uses = None
        expires_at = None
        if mode == "usage":
            max_uses = int_value(payload, "max_uses", 10, 1, 1000000)
        elif mode == "time":
            try:
                expires_at = self.subscription_expires_at(payload)
            except ValueError:
                return self.send_json({"error": "过期时间格式不正确"}, HTTPStatus.BAD_REQUEST)
        elif mode == "either":
            max_uses = int_value(payload, "max_uses", 10, 1, 1000000)
            try:
                expires_at = self.subscription_expires_at(payload)
            except ValueError:
                return self.send_json({"error": "过期时间格式不正确"}, HTTPStatus.BAD_REQUEST)
        else:
            return self.send_json({"error": "失效方式只能是次数、时间或任一条件"}, HTTPStatus.BAD_REQUEST)
        token = secrets.token_hex(16)
        with NodeDatabase(DATABASE) as database:
            claim_config = database.claim_code_config()
            link = database.create_subscription_link(
                token,
                name,
                mode,
                max_uses,
                expires_at,
                template,
                remark,
                export_limit,
                str(claim_config["version"]),
            )
            decorated = self.decorate_subscription_link(link, claim_config)
        LOG_BUS.emit("subscription", "已生成订阅链接 | " + name + " | " + decorated["url"], "success")
        return self.send_json({"subscription": decorated})

    def subscription_expires_at(self, payload: dict) -> str:
        raw = str(payload.get("expires_at", "")).strip()
        if raw:
            raw = raw.replace("T", " ")
            if len(raw) == 16:
                raw += ":00"
            datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            return raw
        hours = int_value(payload, "expires_hours", 24, 1, 24 * 365)
        return (beijing_now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    def set_subscription_enabled(self, token: str, enabled: bool) -> None:
        if not token:
            return self.send_json({"error": "缺少订阅 token"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            link = database.set_subscription_enabled(token, enabled)
            if not link:
                return self.send_json({"error": "订阅链接不存在"}, HTTPStatus.NOT_FOUND)
            return self.send_json({"subscription": self.decorate_subscription_link(link, database.claim_code_config())})

    def delete_subscription(self, token: str) -> None:
        if not token:
            return self.send_json({"error": "缺少订阅 token"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            deleted = database.delete_subscription_link(token)
        if not deleted:
            return self.send_json({"error": "订阅链接不存在"}, HTTPStatus.NOT_FOUND)
        return self.send_json({"deleted": True})

    def test_subscription_format(self, token: str, payload: dict) -> None:
        if not token:
            return self.send_json({"error": "缺少订阅 token"}, HTTPStatus.BAD_REQUEST)
        target_id = self.subscription_target_from_query("", payload)
        started = time.monotonic()
        with NodeDatabase(DATABASE) as database:
            link = database.subscription_link(token)
            claim_config = database.claim_code_config()
            if not link:
                return self.send_json({"error": "订阅链接不存在"}, HTTPStatus.NOT_FOUND)
            available, status, reason = self.subscription_available(link, claim_config, enforce_claim_version=True)
            if not available:
                return self.send_json({"error": reason, "status": "expired"}, status)
            try:
                result = self.subscription_output(database, link, claim_config, target_id)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                message = "调用 Sub-Store 服务失败，" + sub_store_unreachable_message(database.subscription_converter_config().get("backend_url"), reason)
                return self.send_json({"error": message}, HTTPStatus.BAD_GATEWAY)
            except TimeoutError:
                return self.send_json({"error": "调用 Sub-Store 服务超时"}, HTTPStatus.GATEWAY_TIMEOUT)
        content = str(result["content"])
        preview = content[:1200]
        return self.send_json({
            "ok": True,
            "token": token,
            "target_id": result["target_id"],
            "target_name": result["target_name"],
            "node_count": int(result["count"]),
            "content_type": result["content_type"],
            "bytes": len(content.encode("utf-8")),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "preview": preview,
            "truncated": len(preview) < len(content),
        })

    def set_repo_enabled(self, repo: str, enabled: bool) -> None:
        repo = normalize_repo(urllib.parse.unquote(repo))
        if not repo:
            return self.send_json({"error": "仓库地址不正确"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            item = database.set_collector_repo_enabled(repo, enabled)
            items = database.collector_repo_items(DEFAULT_REPOS)
            repos = [entry["repo"] for entry in items if entry["enabled"]]
        LOG_BUS.emit("collector", ("已启用仓库 | " if enabled else "已禁用仓库 | ") + repo, "success")
        return self.send_json({"repo": item, "repos": repos, "items": items, "count": len(repos), "total": len(items)})

    def decorate_subscription_links(self, links: List[dict], claim_config: Optional[dict] = None) -> List[dict]:
        return [self.decorate_subscription_link(link, claim_config) for link in links]

    def decorate_subscription_link(self, link: dict, claim_config: Optional[dict] = None) -> dict:
        available, status, reason = self.subscription_available(link, claim_config, enforce_claim_version=claim_config is not None)
        decorated = dict(link)
        decorated["available"] = available
        decorated["status"] = "有效" if available else reason
        decorated["status_code"] = int(status)
        decorated["url"] = self.public_origin() + "/sub/" + str(link["token"])
        decorated["format_urls"] = self.subscription_format_urls(str(link["token"]))
        decorated["current_claim_code_version"] = str((claim_config or {}).get("version") or "")
        return decorated

    def subscription_format_urls(self, token: str) -> List[dict]:
        base_url = self.public_origin() + "/sub/" + token
        targets = [{"id": "base64", "name": "通用 Base64"}, {"id": "raw", "name": "原始节点"}]
        targets.extend(subscription_converter_targets())
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "url": base_url if item["id"] == "base64" else base_url + "?target=" + urllib.parse.quote(str(item["id"])),
            }
            for item in targets
        ]

    def public_origin(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto", "")
        host = self.headers.get("X-Forwarded-Host", "") or self.headers.get("Host", "")
        if not proto:
            proto = "https" if self.is_https() else "http"
        return proto + "://" + host if host else ""

    def runtime_status(self) -> dict:
        xray_default = ROOT / "tools" / "xray" / "xray"
        try:
            xray_path = str(resolve_xray_path(xray_default))
            xray_available = True
        except FileNotFoundError:
            xray_path = str(xray_default)
            xray_available = False
        return {
            "root": str(ROOT),
            "database": str(DATABASE),
            "web_root": str(WEB_ROOT),
            "runtime_log": str(CONFIG.runtime_log),
            "xray": xray_path,
            "xray_available": xray_available,
            "geoip": str(Path(xray_path).parent / "geoip.dat"),
            "host": CONFIG.host,
            "port": CONFIG.port,
            "admin_base_path": ADMIN_BASE_PATH,
            "task_stop_timeout": CONFIG.task_stop_timeout,
        }

    def admin_route(self, path: str) -> Optional[str]:
        if path == ADMIN_BASE_PATH:
            return "/"
        if path.startswith(ADMIN_BASE_PATH + "/"):
            return path[len(ADMIN_BASE_PATH):] or "/"
        return None

    def current_user(self) -> Optional[dict]:
        token = cookie_token(self.headers.get("Cookie", ""))
        if not token:
            return None
        with NodeDatabase(DATABASE) as database:
            return database.admin_user_by_session(token_hash(token))

    def login(self, payload: dict) -> None:
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        with NodeDatabase(DATABASE) as database:
            database.prune_admin_sessions()
            user = database.admin_user_by_username(username)
            if not user or not verify_password(password, str(user["password_hash"])):
                time.sleep(0.35)
                LOG_BUS.emit("auth", "后台登录失败 | 用户名 " + (username or "-"), "warning")
                return self.send_json({"error": "用户名或密码错误"}, HTTPStatus.UNAUTHORIZED)
            token = create_session(database, int(user["id"]), self.client_ip(), self.headers.get("User-Agent", ""))
        LOG_BUS.emit("auth", "后台登录成功 | 用户名 " + username, "success")
        return self.send_json(
            {"authenticated": True, "user": {"id": user["id"], "username": user["username"]}},
            headers={"Set-Cookie": cookie_header(token, self.is_https())},
        )

    def logout(self) -> None:
        token = cookie_token(self.headers.get("Cookie", ""))
        if token:
            with NodeDatabase(DATABASE) as database:
                database.delete_admin_session(token_hash(token))
        return self.send_json({"logged_out": True}, headers={"Set-Cookie": clear_cookie_header()})

    def update_account(self, user: dict, payload: dict) -> None:
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        if len(username) < 3:
            return self.send_json({"error": "用户名至少需要 3 个字符"}, HTTPStatus.BAD_REQUEST)
        if password and len(password) < 8:
            return self.send_json({"error": "新密码至少需要 8 个字符"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            updated = database.update_admin_credentials(
                int(user["id"]),
                username,
                hash_password(password) if password else None,
            )
        LOG_BUS.emit("auth", "后台账号信息已更新 | 用户名 " + username, "success")
        return self.send_json({"user": updated})

    def client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return self.client_address[0] if self.client_address else ""

    def is_https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def task_response(self, name: str, changed: bool, reason: str = "ok") -> None:
        status = TASKS[name].status()
        status_code = HTTPStatus.OK if changed or reason == "ok" else HTTPStatus.CONFLICT
        return self.send_json({"changed": changed, "task": name, "status": status, "reason": reason}, status_code)

    def send_events(self, parsed) -> None:
        query = urllib.parse.parse_qs(parsed.query)
        cursor = int(query.get("cursor", ["0"])[0])
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                events = LOG_BUS.after(cursor)
                if events:
                    for event in events:
                        cursor = event["id"]
                        payload = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(("id: " + str(cursor) + "\ndata: " + payload + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                else:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                with LOG_BUS.condition:
                    LOG_BUS.condition.wait(timeout=2)
        except (BrokenPipeError, ConnectionResetError):
            return

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK, headers: Optional[dict] = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if not target.is_file():
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DashboardServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        error = sys.exception()
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def main() -> int:
    with NodeDatabase(DATABASE) as database:
        ensure_default_admin(database)
    AUTO_CONTROLLER.ensure_running()
    ensure_bot_auto_run()
    host = CONFIG.host
    port = CONFIG.port
    LOG_BUS.emit("system", "鑺傜偣鎺у埗鍙板惎鍔?| http://" + host + ":" + str(port) + ADMIN_BASE_PATH, "success")

    def handle_signal(signum, _frame) -> None:
        stop_all_tasks("鏀跺埌绯荤粺閫€鍑轰俊鍙?" + str(signum) + "锛屾鍦ㄥ仠姝㈠瓙浠诲姟", wait=True)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print("Node dashboard: http://" + host + ":" + str(port) + ADMIN_BASE_PATH, flush=True)
    try:
        DashboardServer((host, port), DashboardHandler).serve_forever()
    except KeyboardInterrupt:
        print("\nNode dashboard stopped.", flush=True)
        LOG_BUS.emit("system", "鑺傜偣鎺у埗鍙板凡鍋滄", "warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
