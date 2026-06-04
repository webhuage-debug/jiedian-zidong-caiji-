#!/usr/bin/env python3
"""Local web dashboard for node collection, validation, and database browsing."""

from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from app_time import beijing_now
from node_database import NodeDatabase
from node_collector import DEFAULT_REPOS
from node_processor import DEFAULT_RENAME_TEMPLATE, processed_nodes, subscription_base64
from runtime_tasks import LogBus, ManagedTask


ROOT = CONFIG.root
DATABASE = CONFIG.database
WEB_ROOT = CONFIG.web_root
ADMIN_BASE_PATH = CONFIG.admin_base_path
SUBCONVERTER_URL = os.environ.get("HUAGE_SUBCONVERTER_URL", "http://127.0.0.1:25500").rstrip("/")
DIRECT_SUBSCRIPTION_TARGETS = {"", "v2ray", "v2rayn", "v2rayng", "shadowrocket"}
CONVERTED_SUBSCRIPTION_TARGETS = {
    "clash": {"target": "clash"},
    "singbox": {"target": "singbox"},
    "surge": {"target": "surge", "ver": "4"},
}
ASIA_VALID_LOW_WATERMARK = int(os.environ.get("HUAGE_ASIA_VALID_LOW_WATERMARK", "10"))


LOG_BUS = LogBus(CONFIG.log_buffer_size, CONFIG.runtime_log)
TASKS: Dict[str, ManagedTask] = {
    "collector": ManagedTask("collector", LOG_BUS),
    "validator": ManagedTask("validator", LOG_BUS),
    "bot": ManagedTask("bot", LOG_BUS),
}


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


def int_value(payload: dict, name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(payload.get(name, default))
    return max(minimum, min(value, maximum))


def float_value(payload: dict, name: str, default: float, minimum: float, maximum: float) -> float:
    value = float(payload.get(name, default))
    return max(minimum, min(value, maximum))


def log_level_value(value: object) -> str:
    level = str(value or "detail")
    return level if level in ("compact", "detail", "nodes") else "detail"


def build_collector_command(payload: dict) -> List[str]:
    delay = float_value(payload, "delay", 1.0, 0, 30)
    jitter = float_value(payload, "delay_jitter", 0.5, 0, 30)
    workers = int_value(payload, "workers", 5, 1, 12)
    max_depth = int_value(payload, "max_depth", 8, 0, 20)
    log_level = log_level_value(payload.get("log_level", "detail"))
    repos = load_repo_config()
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
    if not payload.get("valid_only"):
        command.append("--random")
    if payload.get("revalidate"):
        command.append("--revalidate")
    if payload.get("valid_only"):
        command.append("--valid-only")
    if payload.get("asia_first"):
        command.append("--asia-first")
    return command


def build_bot_command() -> List[str]:
    return [sys.executable, "-u", "bot_service.py", "--database", str(DATABASE)]


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
        LOG_BUS.emit("bot", "BOT 已设置自动运行，但尚未填写 Token", "warning")
        return False
    if task_is_running("bot"):
        return False
    changed = TASKS["bot"].start(build_bot_command())
    if changed:
        LOG_BUS.emit("bot", "已根据数据库配置自动启动 BOT", "success")
    return changed


MAINTENANCE_THREAD: Optional[threading.Thread] = None


def run_maintenance(emit_result: bool = True) -> None:
    try:
        with NodeDatabase(DATABASE) as database:
            removed_sessions = database.prune_admin_sessions()
            removed_bot_logs = database.prune_bot_message_logs(
                CONFIG.bot_message_log_retention_days,
                CONFIG.bot_message_log_max_rows,
            )
            database.checkpoint()
    except Exception as exc:
        LOG_BUS.emit("maintenance", "自动清理失败 | " + str(exc), "warning")
        return
    removed_total = removed_sessions + removed_bot_logs["age"] + removed_bot_logs["count"]
    if emit_result and removed_total:
        LOG_BUS.emit(
            "maintenance",
            "自动清理完成 | 过期会话 "
            + str(removed_sessions)
            + " | Bot日志按时间 "
            + str(removed_bot_logs["age"])
            + " | Bot日志按数量 "
            + str(removed_bot_logs["count"]),
            "success",
        )


def start_maintenance_worker() -> None:
    global MAINTENANCE_THREAD
    if MAINTENANCE_THREAD and MAINTENANCE_THREAD.is_alive():
        return

    def loop() -> None:
        interval = max(1, CONFIG.maintenance_interval_hours) * 3600
        while True:
            time.sleep(interval)
            run_maintenance()

    MAINTENANCE_THREAD = threading.Thread(target=loop, name="maintenance", daemon=True)
    MAINTENANCE_THREAD.start()


def task_is_running(name: str) -> bool:
    return bool(TASKS[name].status()["running"])


def start_managed_task(name: str, command: List[str], source: str = "manual") -> tuple[bool, str]:
    other = "validator" if name == "collector" else "collector"
    if task_is_running(other):
        return False, "验证运行时不能采集，采集运行时不能验证"
    if task_is_running(name):
        return False, "任务已经在运行"
    changed = TASKS[name].start(command)
    if changed and source == "auto":
        LOG_BUS.emit("auto", ("已启动采集任务" if name == "collector" else "已启动验证任务"), "success")
    return changed, "ok"


class AutoController:
    def __init__(self, log_bus: LogBus):
        self.log_bus = log_bus
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.phase = "idle"
        self.last_reason = "自动控制尚未启动"
        self.collect_baseline = 0
        self.collect_target = 0
        self.validate_baseline = 0
        self.validate_target = 0
        self.started_at: Optional[float] = None

    def start(self) -> None:
        with NodeDatabase(DATABASE) as database:
            database.update_auto_config({"enabled": True})
        with self.lock:
            self.last_reason = "已开启自动控制，等待阈值检查"
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
        self.log_bus.emit("auto", "全自动控制台已开启", "success")

    def stop(self) -> None:
        with NodeDatabase(DATABASE) as database:
            database.update_auto_config({"enabled": False})
        with self.lock:
            self.phase = "stopping"
            self.last_reason = "用户关闭自动控制，正在停止所有任务"
        TASKS["collector"].stop()
        TASKS["validator"].stop()
        self.log_bus.emit("auto", "全自动控制台已关闭，已请求停止采集和验证", "warning")

    def save_config(self, payload: dict) -> dict:
        cleaned = {
            "valid_low_watermark": int_value(payload, "valid_low_watermark", 20, 0, 1000000),
            "collect_insert_target": int_value(payload, "collect_insert_target", 200, 1, 1000000),
            "validate_valid_target": int_value(payload, "validate_valid_target", 20, 1, 1000000),
            "check_interval_minutes": int_value(payload, "check_interval_minutes", 5, 1, 1440),
            "collector_workers": int_value(payload, "collector_workers", 5, 1, 12),
            "collector_depth": int_value(payload, "collector_depth", 8, 0, 20),
            "collector_delay": float_value(payload, "collector_delay", 1.0, 0, 30),
            "collector_jitter": float_value(payload, "collector_jitter", 0.5, 0, 30),
            "collector_log_level": log_level_value(payload.get("collector_log_level", "detail")),
            "validator_workers": int_value(payload, "validator_workers", 10, 1, 50),
            "validator_rounds": int_value(payload, "validator_rounds", 3, 1, 10),
            "validator_timeout": int_value(payload, "validator_timeout", 8, 2, 60),
        }
        if "enabled" in payload:
            cleaned["enabled"] = bool(payload.get("enabled"))
        with NodeDatabase(DATABASE) as database:
            config = database.update_auto_config(cleaned)
        self.log_bus.emit("auto", "自动控制参数已保存到数据库", "success")
        return config

    def status(self) -> dict:
        with NodeDatabase(DATABASE) as database:
            config = database.auto_config()
            stats = database.stats()
        with self.lock:
            phase = self.phase
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
            "phase": phase,
            "last_reason": reason,
            "started_at": started_at,
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
                        self.last_reason = "自动控制已关闭"
                return
            self._tick(config, stats)
            time.sleep(int(config["check_interval_minutes"]) * 60)

    def _tick(self, config: dict, stats: dict) -> None:
        collector_running = task_is_running("collector")
        validator_running = task_is_running("validator")
        valid_count = int(stats.get("valid_nodes", 0))
        asia_valid_count = int(stats.get("valid_asia_nodes", 0))
        pending_count = int(stats.get("total_nodes", 0))
        if collector_running and validator_running:
            TASKS["validator"].stop()
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
            if self.phase == "rechecking":
                self._set("rechecking", "正在复检现有有效节点")
                return
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
        if self.phase == "rechecking":
            if valid_count < int(config["valid_low_watermark"]) or asia_valid_count < ASIA_VALID_LOW_WATERMARK:
                if pending_count > 0:
                    self._start_validator(config, valid_count, "复检后有效节点或亚洲节点低于阈值，正在从节点库优先补齐亚洲线路", asia_first=True)
                    return
                self._start_collector(config, valid_count)
                return
            self._set("idle", "复检完成，有效节点数量充足")
            return
        if valid_count < int(config["valid_low_watermark"]):
            if pending_count > 0:
                asia_first = asia_valid_count < ASIA_VALID_LOW_WATERMARK
                reason = "有效节点低于阈值，正在优先补齐亚洲线路" if asia_first else "有效节点低于阈值，但节点库仍有待验证库存，优先启动验证"
                self._start_validator(config, valid_count, reason, asia_first=asia_first)
                return
            self._start_collector(config, valid_count)
            return
        if asia_valid_count < ASIA_VALID_LOW_WATERMARK:
            if pending_count > 0:
                self._start_validator(config, valid_count, "亚洲有效节点不足，正在优先验证亚洲候选线路", asia_first=True)
                return
            self._start_collector(config, valid_count)
            return
        self._start_valid_recheck(config, valid_count)

    def _start_collector(self, config: dict, valid_count: int) -> None:
        payload = {
            "workers": config["collector_workers"],
            "max_depth": config["collector_depth"],
            "delay": config["collector_delay"],
            "delay_jitter": config["collector_jitter"],
            "log_level": config["collector_log_level"],
        }
        with self.lock:
            self.collect_baseline = 0
            self.collect_target = int(config["collect_insert_target"])
            self.validate_baseline = valid_count
            self.validate_target = int(config["validate_valid_target"])
            self.started_at = time.time()
        changed, reason = start_managed_task("collector", build_collector_command(payload), "auto")
        if changed:
            self._set("collecting", "有效节点低于阈值且节点库为空，已自动启动采集")
        else:
            self._set("idle", "自动采集未启动：" + reason)

    def _start_validator(self, config: dict, valid_count: int, reason_text: str, asia_first: bool = False) -> None:
        payload = {
            "workers": config["validator_workers"],
            "limit": self._auto_validator_limit(config),
            "rounds": config["validator_rounds"],
            "timeout": config["validator_timeout"],
            "asia_first": asia_first,
        }
        with self.lock:
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

    def _start_valid_recheck(self, config: dict, valid_count: int) -> None:
        payload = {
            "workers": config["validator_workers"],
            "limit": self._auto_recheck_limit(valid_count),
            "rounds": config["validator_rounds"],
            "timeout": config["validator_timeout"],
            "valid_only": True,
        }
        with self.lock:
            self.validate_baseline = valid_count
            self.validate_target = 0
            self.started_at = time.time()
        changed, reason = start_managed_task("validator", build_validator_command(payload), "auto")
        if changed:
            self._set("rechecking", "有效节点数量充足，已启动本轮有效节点复检")
        else:
            self._set("idle", "自动复检未启动：" + reason)

    def _auto_validator_limit(self, config: dict) -> int:
        target = int(config["validate_valid_target"])
        return min(1000, max(50, target * 5))

    def _auto_recheck_limit(self, valid_count: int) -> int:
        return min(10, max(1, valid_count))

    def _set(self, phase: str, reason: str) -> None:
        should_emit = False
        with self.lock:
            if self.phase != phase or self.last_reason != reason:
                should_emit = True
            self.phase = phase
            self.last_reason = reason
        if should_emit:
            self.log_bus.emit("auto", reason, "info")


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
            return self.public_subscription(parsed.path, parsed.query)
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
                return self.send_json({"error": "请先登录后台"}, HTTPStatus.UNAUTHORIZED)
        if route == "/api/me":
            user = self.current_user()
            return self.send_json({"authenticated": bool(user), "user": user})
        if route == "/api/status":
            return self.send_json(self.dashboard_status())
        if route == "/api/runtime":
            return self.send_json(self.runtime_status())
        if route == "/api/auto":
            return self.send_json(AUTO_CONTROLLER.status())
        if route == "/api/repos":
            repos = load_repo_config()
            return self.send_json({"repos": repos, "count": len(repos)})
        if route == "/api/source-profiles":
            query = urllib.parse.parse_qs(parsed.query)
            limit = min(100, max(1, int(query.get("limit", ["20"])[0])))
            with NodeDatabase(DATABASE) as database:
                return self.send_json({"profiles": database.top_source_profiles(limit)})
        if route == "/api/subscriptions":
            with NodeDatabase(DATABASE) as database:
                return self.send_json({"subscriptions": self.decorate_subscription_links(database.subscription_links())})
        if route == "/api/claim-code/config":
            with NodeDatabase(DATABASE) as database:
                return self.send_json({"config": database.claim_config()})
        if route == "/api/bot":
            with NodeDatabase(DATABASE) as database:
                config = database.bot_config(mask_secrets=True)
                return self.send_json({
                    "config": config,
                    "messages": database.bot_message_logs(),
                    **bot_runtime_status(config),
                })
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
            with NodeDatabase(DATABASE) as database:
                config = database.processing_config()
                nodes = database.valid_nodes(CONFIG.subscription_node_limit, 0)
            result = subscription_base64(nodes, config["rename_template"])
            return self.send_text(result["subscription"] + "\n", "text/plain; charset=utf-8")
        if route == "/api/subscription/plain":
            with NodeDatabase(DATABASE) as database:
                config = database.processing_config()
                nodes = database.valid_nodes(CONFIG.subscription_node_limit, 0)
            rows = processed_nodes(nodes, config["rename_template"])
            return self.send_text("\n".join(row["uri"] for row in rows) + "\n", "text/plain; charset=utf-8")
        if route == "/api/events":
            return self.send_events(parsed)
        return self.send_static(route)

    def do_POST(self) -> None:
        payload = self.read_json()
        parsed = urllib.parse.urlsplit(self.path)
        route = self.admin_route(parsed.path)
        if route is None:
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if route == "/api/login":
            return self.login(payload)
        user = self.current_user()
        if not user:
            return self.send_json({"error": "请先登录后台"}, HTTPStatus.UNAUTHORIZED)
        if route == "/api/logout":
            return self.logout()
        if route == "/api/account":
            return self.update_account(user, payload)
        if route == "/api/collector/start":
            repos = load_repo_config()
            LOG_BUS.emit("collector", "本次采集将随机仓库顺序，仓库数 " + str(len(repos)), "info")
            changed, reason = start_managed_task("collector", build_collector_command(payload))
            return self.task_response("collector", changed, reason)
        if route == "/api/collector/stop":
            return self.task_response("collector", TASKS["collector"].stop(), "ok")
        if route == "/api/validator/start":
            changed, reason = start_managed_task("validator", build_validator_command(payload))
            return self.task_response("validator", changed, reason)
        if route == "/api/validator/stop":
            return self.task_response("validator", TASKS["validator"].stop(), "ok")
        if route == "/api/bot/start":
            changed = TASKS["bot"].start(build_bot_command())
            return self.task_response("bot", changed, "ok" if changed else "BOT 机器人已经在运行")
        if route == "/api/bot/stop":
            return self.task_response("bot", TASKS["bot"].stop(), "ok")
        if route == "/api/bot/disable":
            with NodeDatabase(DATABASE) as database:
                config = database.update_bot_config({"auto_run": False})
            changed = TASKS["bot"].stop()
            LOG_BUS.emit("bot", "已关闭 BOT 自动运行，并请求停止当前 BOT 任务", "warning")
            return self.send_json({"changed": changed, "config": config, **bot_runtime_status(config)})
        if route == "/api/bot/config":
            return self.update_bot_config(payload)
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
            template = str(payload.get("rename_template", "")).strip()
            with NodeDatabase(DATABASE) as database:
                if not template:
                    template = database.processing_config()["rename_template"]
                nodes = database.valid_nodes(CONFIG.subscription_node_limit, 0)
            result = subscription_base64(nodes, template)
            LOG_BUS.emit("processor", "已生成 Base64 订阅，节点数 " + str(result["count"]), "success")
            return self.send_json({"template": template, **result})
        if route == "/api/logs/clear":
            LOG_BUS.clear()
            return self.send_json({"cleared": True})
        if route == "/api/subscriptions":
            return self.create_subscription(payload)
        if route == "/api/claim-code/config":
            return self.update_claim_config(payload)
        if route.startswith("/api/subscriptions/"):
            token = route.removeprefix("/api/subscriptions/").strip("/")
            if route.endswith("/disable"):
                return self.set_subscription_enabled(token.removesuffix("/disable").strip("/"), False)
            if route.endswith("/enable"):
                return self.set_subscription_enabled(token.removesuffix("/enable").strip("/"), True)
            if route.endswith("/delete"):
                return self.delete_subscription(token.removesuffix("/delete").strip("/"))
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
                return self.send_json({"error": "至少需要一个有效仓库地址"}, HTTPStatus.BAD_REQUEST)
            save_repo_config(normalized)
            LOG_BUS.emit("collector", "仓库列表已保存，仓库数 " + str(len(normalized)), "success")
            return self.send_json({"repos": normalized, "count": len(normalized)})
        if route == "/api/repos/reset":
            save_repo_config(list(DEFAULT_REPOS))
            LOG_BUS.emit("collector", "仓库列表已恢复默认，仓库数 " + str(len(DEFAULT_REPOS)), "success")
            return self.send_json({"repos": list(DEFAULT_REPOS), "count": len(DEFAULT_REPOS)})
        return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def dashboard_status(self) -> dict:
        with NodeDatabase(DATABASE) as database:
            repos = database.collector_repos(DEFAULT_REPOS)
            return {
                "tasks": {name: task.status() for name, task in TASKS.items()},
                "auto": AUTO_CONTROLLER.status(),
                "database": database.stats(),
                "repos": {"items": repos, "count": len(repos)},
            }

    def health_status(self) -> dict:
        return {
            "ok": True,
            "tasks": {name: task.status()["running"] for name, task in TASKS.items()},
        }

    def public_subscription(self, path: str, query: str = "") -> None:
        token = path.removeprefix("/sub/").strip("/")
        if not token or "/" in token:
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        params = urllib.parse.parse_qs(query)
        target = str(params.get("target", [""])[0]).strip().lower()
        if target not in DIRECT_SUBSCRIPTION_TARGETS and target not in CONVERTED_SUBSCRIPTION_TARGETS:
            return self.send_json({"error": "不支持的订阅格式"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            link = database.subscription_link(token)
            if not link:
                return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            available, status, reason = self.subscription_available(link)
            if not available:
                return self.send_json({"error": reason}, status)
            if target in CONVERTED_SUBSCRIPTION_TARGETS:
                return self.convert_subscription(token, target, str(link["name"]))
            config = database.processing_config()
            template = link["rename_template"] or config["rename_template"]
            nodes = database.valid_nodes(CONFIG.subscription_node_limit, 0)
            result = subscription_base64(nodes, template)
            database.touch_subscription_link(token, self.client_ip())
        LOG_BUS.emit("subscription", "订阅已访问 | " + str(link["name"]) + " | 格式 " + (target or "v2ray") + " | 节点 " + str(result["count"]), "info")
        return self.send_text(result["subscription"] + "\n", "text/plain; charset=utf-8")

    def convert_subscription(self, token: str, target: str, name: str) -> None:
        source_url = self.public_origin().rstrip("/") + "/sub/" + token
        if not source_url.startswith("http"):
            source_url = "http://" + CONFIG.host + ":" + str(CONFIG.port) + "/sub/" + token
        options = dict(CONVERTED_SUBSCRIPTION_TARGETS[target])
        options["url"] = source_url
        converter_url = SUBCONVERTER_URL + "/sub?" + urllib.parse.urlencode(options)
        try:
            with urllib.request.urlopen(converter_url, timeout=30) as response:
                body = response.read().decode("utf-8", errors="replace")
        except OSError as error:
            LOG_BUS.emit("subscription", "订阅转换失败 | " + target + " | " + str(error), "error")
            return self.send_json({"error": "订阅转换服务不可用，请稍后再试"}, HTTPStatus.BAD_GATEWAY)
        LOG_BUS.emit("subscription", "订阅已转换 | " + name + " | 格式 " + target, "info")
        return self.send_text(body, "text/plain; charset=utf-8")

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
            message = "验证任务已建立。YouTube OAuth 校验入口将在下一阶段接入。"
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
            "auto_run", "reply_message", "public_base_url", "verify_link_minutes", "welcome_message", "unverified_message", "success_message",
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

    def subscription_available(self, link: dict) -> tuple[bool, HTTPStatus, str]:
        if not link["enabled"]:
            return False, HTTPStatus.FORBIDDEN, "订阅链接已禁用"
        link_version = str(link.get("claim_version") or "")
        if link_version:
            with NodeDatabase(DATABASE) as database:
                current_version = str(database.claim_config().get("claim_version") or "")
            if current_version and link_version != current_version:
                return False, HTTPStatus.GONE, "领取口令已更新，请重新领取订阅链接"
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
            claim_version = str(database.claim_config().get("claim_version") or "")
            link = database.create_subscription_link(
                token, name, mode, max_uses, expires_at, template, remark,
                claim_version=claim_version,
            )
            decorated = self.decorate_subscription_link(link)
        LOG_BUS.emit("subscription", "已生成订阅链接 | " + name + " | " + decorated["url"], "success")
        return self.send_json({"subscription": decorated})

    def update_claim_config(self, payload: dict) -> None:
        values = {
            "youtube_channel_url": str(payload.get("youtube_channel_url", "")).strip(),
            "claim_code": str(payload.get("claim_code", "")).strip(),
            "claim_version": str(payload.get("claim_version", "")).strip(),
            "claim_expires_at": str(payload.get("claim_expires_at", "")).strip(),
            "daily_claim_limit": int_value(payload, "daily_claim_limit", 1, 1, 100),
            "group_dm_success_message": str(payload.get("group_dm_success_message", "")).strip(),
            "group_dm_failed_message": str(payload.get("group_dm_failed_message", "")).strip(),
            "claim_prompt_message": str(payload.get("claim_prompt_message", "")).strip(),
            "youtube_button_message": str(payload.get("youtube_button_message", "")).strip(),
            "ask_code_message": str(payload.get("ask_code_message", "")).strip(),
            "wrong_code_message": str(payload.get("wrong_code_message", "")).strip(),
            "expired_code_message": str(payload.get("expired_code_message", "")).strip(),
            "limit_message": str(payload.get("limit_message", "")).strip(),
            "success_message": str(payload.get("success_message", "")).strip(),
        }
        if values["claim_expires_at"]:
            values["claim_expires_at"] = values["claim_expires_at"].replace("T", " ")
            if len(values["claim_expires_at"]) == 16:
                values["claim_expires_at"] += ":00"
            try:
                datetime.strptime(values["claim_expires_at"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return self.send_json({"error": "口令有效期格式不正确"}, HTTPStatus.BAD_REQUEST)
        if not values["claim_version"]:
            values["claim_version"] = "口令-" + beijing_now().strftime("%Y%m%d%H%M%S")
        with NodeDatabase(DATABASE) as database:
            config = database.update_claim_config(values)
        LOG_BUS.emit("claim", "领取口令配置已保存 | 当前版本 " + str(config.get("claim_version", "")), "success")
        return self.send_json({"config": config})

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
            return self.send_json({"subscription": self.decorate_subscription_link(link)})

    def delete_subscription(self, token: str) -> None:
        if not token:
            return self.send_json({"error": "缺少订阅 token"}, HTTPStatus.BAD_REQUEST)
        with NodeDatabase(DATABASE) as database:
            deleted = database.delete_subscription_link(token)
        if not deleted:
            return self.send_json({"error": "订阅链接不存在"}, HTTPStatus.NOT_FOUND)
        return self.send_json({"deleted": True})

    def decorate_subscription_links(self, links: List[dict]) -> List[dict]:
        return [self.decorate_subscription_link(link) for link in links]

    def decorate_subscription_link(self, link: dict) -> dict:
        available, status, reason = self.subscription_available(link)
        decorated = dict(link)
        decorated["available"] = available
        decorated["status"] = "有效" if available else reason
        decorated["status_code"] = int(status)
        decorated["url"] = self.public_origin() + "/sub/" + str(link["token"])
        return decorated

    def public_origin(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto", "")
        host = self.headers.get("X-Forwarded-Host", "") or self.headers.get("Host", "")
        if not proto:
            proto = "https" if self.is_https() else "http"
        return proto + "://" + host if host else ""

    def runtime_status(self) -> dict:
        return {
            "root": str(ROOT),
            "database": str(DATABASE),
            "web_root": str(WEB_ROOT),
            "runtime_log": str(CONFIG.runtime_log),
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
    run_maintenance()
    start_maintenance_worker()
    AUTO_CONTROLLER.ensure_running()
    ensure_bot_auto_run()
    host = CONFIG.host
    port = CONFIG.port
    LOG_BUS.emit("system", "节点控制台启动 | http://" + host + ":" + str(port) + ADMIN_BASE_PATH, "success")

    def handle_signal(signum, _frame) -> None:
        stop_all_tasks("收到系统退出信号 " + str(signum) + "，正在停止子任务", wait=True)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print("Node dashboard: http://" + host + ":" + str(port) + ADMIN_BASE_PATH, flush=True)
    try:
        DashboardServer((host, port), DashboardHandler).serve_forever()
    except KeyboardInterrupt:
        print("\nNode dashboard stopped.", flush=True)
        LOG_BUS.emit("system", "节点控制台已停止", "warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
