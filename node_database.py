#!/usr/bin/env python3
"""SQLite storage shared by the crawler and Xray validator."""

from __future__ import annotations

import os
import json
import base64
import hashlib
import re
import sqlite3
import urllib.parse
from datetime import timedelta
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from app_time import beijing_now, beijing_timestamp
from node_region import is_publishable_region, publish_region
from subscription_filter import (
    DEFAULT_SUBSCRIPTION_TARGET,
    MAX_SUBSCRIPTION_TARGET,
    MIN_SUBSCRIPTION_TARGET,
    final_subscription_nodes,
    normalize_subscription_limit,
    subscription_quality_score,
    subscription_sort_key,
)


def normalize_bot_username_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("@"):
        text = text[1:]
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in ("t.me", "telegram.me"):
        text = parsed.path.strip("/").split("/", 1)[0]
    return text.strip().lstrip("@")


def bot_private_start_url_value(username: object, payload: str = "claim") -> str:
    normalized = normalize_bot_username_value(username)
    if not normalized:
        return ""
    return "https://t.me/" + normalized + "?start=" + urllib.parse.quote(str(payload or "claim"))


def decode_uri_b64(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8", errors="replace")


CF_SOURCE_REPOS = {
    "free-nodes/v2rayfree",
    "zengfr/free-vpn-subscribe",
    "FreeFolksOn/abc-configs-free-vpn-proxy-list",
    "mehdirzfx/v2ray-sub",
    "NiREvil/vless",
    "mermeroo/V2RAY-CLASH-BASE64-Subscription.Links",
    "Surfboardv2ray/v2ray-worker-sub",
}

CF_REFERENCE_REPOS = {
    "zizifn/edgetunnel",
    "cmliu/edgetunnel",
    "Vauth/vless-cf",
    "yonggekkk/Cloudflare-vless-trojan",
    "vfarid/v2ray-worker",
    "zhu327/workers-tunnel",
    "6Kmfi6HP/EDtunnel",
    "Surfboardv2ray/Trojan-worker",
    "henrysheep256/Subscription-Generator",
    "dead-man1/CF-Worker-Sub-Manager",
    "NiREvil/bia-pain-bache",
    "7Sageer/sublink-worker",
}

CF_KEYWORDS = (
    "workers.dev", "pages.dev", "trycloudflare.com", "cloudflare", "edgetunnel",
    "worker", "pages", "cf-", "-cf", "cdn-cgi",
)


def _b64_decode_best_effort(value: str) -> str:
    try:
        return decode_uri_b64(value)
    except Exception:
        try:
            return base64.b64decode(value + "=" * (-len(value) % 4)).decode("utf-8", errors="replace")
        except Exception:
            return ""


def _split_host_port(value: str) -> Tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    if text.startswith("[") and "]:" in text:
        host, port = text.rsplit(":", 1)
        return host.strip("[]"), port
    if ":" in text:
        host, port = text.rsplit(":", 1)
        return host, port
    return text, ""


def uri_metadata(uri: str) -> Dict[str, object]:
    text = str(uri or "")
    protocol = protocol_of(text)
    meta: Dict[str, object] = {
        "protocol": protocol,
        "server": "",
        "port": "",
        "network": "",
        "tls": False,
        "uuid_present": False,
        "credential": "",
        "host": "",
        "sni": "",
        "path": "",
        "publish_compatible": False,
        "publish_block_reason": "",
    }
    try:
        if protocol == "vmess":
            payload = text.split("://", 1)[1].split("#", 1)[0]
            data = json.loads(decode_uri_b64(payload))
            meta["server"] = str(data.get("add") or "")
            meta["port"] = str(data.get("port") or "")
            meta["network"] = str(data.get("net") or "")
            meta["tls"] = str(data.get("tls") or "").lower() in ("tls", "true", "1")
            meta["credential"] = str(data.get("id") or "")
            meta["uuid_present"] = bool(str(meta["credential"]).strip())
            meta["host"] = str(data.get("host") or "")
            meta["sni"] = str(data.get("sni") or "")
            meta["path"] = str(data.get("path") or "")
        elif protocol in {"ss", "ssr"}:
            body = text.split("://", 1)[1].split("#", 1)[0].split("?", 1)[0]
            decoded = _b64_decode_best_effort(body)
            candidate = decoded or urllib.parse.unquote(body)
            if "@" in candidate:
                credential, endpoint = candidate.rsplit("@", 1)
                server, port = _split_host_port(endpoint)
            else:
                parsed = urllib.parse.urlsplit(text)
                credential = parsed.username or ""
                server = parsed.hostname or ""
                port = str(parsed.port or "")
            meta["server"] = server
            meta["port"] = str(port or "")
            meta["credential"] = credential
            meta["uuid_present"] = bool(credential)
        else:
            parsed = urllib.parse.urlsplit(text)
            query = urllib.parse.parse_qs(parsed.query)
            meta["server"] = parsed.hostname or ""
            meta["port"] = str(parsed.port or "")
            meta["network"] = (query.get("type") or query.get("net") or [""])[0]
            security = (query.get("security") or [""])[0]
            meta["tls"] = security in ("tls", "reality") or str((query.get("tls") or [""])[0]).lower() in ("1", "true")
            meta["credential"] = urllib.parse.unquote(parsed.username or "")
            meta["uuid_present"] = bool(meta["credential"])
            meta["host"] = (query.get("host") or [""])[0]
            meta["sni"] = (query.get("sni") or query.get("peer") or [""])[0]
            meta["path"] = (query.get("path") or [""])[0]
    except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError, IndexError):
        meta["publish_block_reason"] = "节点格式解析失败"
        return meta
    blocked_protocols = {"tuic", "hysteria", "hysteria2", "hy2"}
    if protocol in blocked_protocols:
        meta["publish_block_reason"] = "协议暂不进入人工发布池"
        return meta
    if str(meta["network"]).lower() == "xhttp":
        meta["publish_block_reason"] = "xhttp 默认不发布"
        return meta
    if not meta["server"] or not meta["port"]:
        meta["publish_block_reason"] = "缺少 server 或 port"
        return meta
    if protocol in {"vless", "vmess", "trojan", "ss", "ssr"} and not meta["uuid_present"]:
        meta["publish_block_reason"] = "缺少 uuid/id"
        return meta
    meta["publish_compatible"] = True
    return meta


def node_fingerprint(uri: str) -> str:
    meta = uri_metadata(uri)
    parts = [
        str(meta.get("protocol") or protocol_of(uri)).lower(),
        str(meta.get("server") or "").lower(),
        str(meta.get("port") or ""),
        str(meta.get("credential") or "").lower(),
        str(meta.get("network") or "").lower(),
        str(meta.get("host") or "").lower(),
        str(meta.get("sni") or "").lower(),
        str(meta.get("path") or ""),
    ]
    if not parts[1] or not parts[2]:
        return hashlib.sha256(str(uri or "").encode("utf-8")).hexdigest()
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def uri_hash(uri: str) -> str:
    return hashlib.sha256(str(uri or "").encode("utf-8")).hexdigest()


def is_cf_candidate_uri(uri: str, repo: str = "", source: str = "") -> bool:
    text = " ".join([str(uri or ""), str(repo or ""), str(source or "")]).lower()
    if str(repo or "") in CF_SOURCE_REPOS or str(repo or "") in CF_REFERENCE_REPOS:
        return True
    if any(keyword in text for keyword in CF_KEYWORDS):
        return True
    if re.search(r"(^|[^a-z0-9])cf([^a-z0-9]|$)", text):
        return True
    return False


ASIA_COUNTRIES = {
    "AE", "AF", "AM", "AZ", "BD", "BH", "BN", "BT", "CN", "GE", "HK", "ID", "IL", "IN",
    "IQ", "IR", "JO", "JP", "KG", "KH", "KP", "KR", "KW", "KZ", "LA", "LB", "LK", "MM",
    "MN", "MO", "MY", "NP", "OM", "PH", "PK", "PS", "QA", "SA", "SG", "SY", "TH", "TJ",
    "TL", "TM", "TR", "TW", "UZ", "VN", "YE",
}


def protocol_of(uri: str) -> str:
    return uri.split("://", 1)[0].lower() if "://" in uri else ""


def is_asia_country(country: str) -> bool:
    return any(part.strip().upper() in ASIA_COUNTRIES for part in (country or "").split(","))


def node_quality_score(seconds: float, validation_count: int, country: str) -> float:
    latency = max(float(seconds or 0), 0.05)
    latency_score = max(0.0, 100.0 - latency * 12.0)
    stability_score = min(int(validation_count or 0), 10) * 4.0
    asia_bonus = 18.0 if is_asia_country(country) else 0.0
    return round(latency_score + stability_score + asia_bonus, 2)


def source_profile_score(
    node_count: int,
    success_count: int,
    fail_count: int,
    valid_count: int = 0,
    invalid_count: int = 0,
    asia_valid_count: int = 0,
) -> int:
    score = (
        int(valid_count or 0) * 200
        + int(asia_valid_count or 0) * 60
        + int(success_count or 0) * 10
        + int(node_count or 0) // 10
        - int(invalid_count or 0) * 5
        - int(fail_count or 0) * 25
    )
    return max(0, score)


def source_profile_tier(score: int, valid_count: int, invalid_count: int) -> str:
    attempts = int(valid_count or 0) + int(invalid_count or 0)
    if int(valid_count or 0) >= 10 and score >= 2000:
        return "A"
    if int(valid_count or 0) >= 3 and score >= 600:
        return "B"
    if attempts >= 20 and int(valid_count or 0) == 0:
        return "D"
    return "C"


def classify_validation_failure(reason: str) -> str:
    lowered = (reason or "").lower()
    if "unsupported by xray" in lowered or "unsupported" in lowered:
        return "unsupported_protocol"
    if "missing server" in lowered or "json" in lowered or "decode" in lowered or "parse" in lowered:
        return "parse_error"
    if "tls" in lowered or "handshake" in lowered or "certificate" in lowered:
        return "tls_error"
    if "timed out" in lowered or "timeout" in lowered or "operation timed out" in lowered:
        return "timeout"
    if "could not resolve" in lowered or "dns" in lowered or "name resolution" in lowered:
        return "dns_error"
    if "connection refused" in lowered or "actively refused" in lowered:
        return "connection_refused"
    if "http " in lowered:
        return "http_error"
    if "未获取代理出口 ip" in lowered or "no proxy ip" in lowered:
        return "no_proxy_ip"
    if "xray" in lowered and ("start" in lowered or "exit" in lowered or "启动" in lowered):
        return "xray_runtime"
    return "other"


class NodeDatabase:
    NODE_UPSERT = """
        INSERT INTO "节点库" (uri, protocol, repo, source, encoding, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
        ON CONFLICT(uri) DO UPDATE SET
            repo = CASE WHEN excluded.repo != '' THEN excluded.repo ELSE "节点库".repo END,
            source = CASE WHEN excluded.source != '' THEN excluded.source ELSE "节点库".source END,
            encoding = CASE WHEN excluded.encoding != '' THEN excluded.encoding ELSE "节点库".encoding END,
            last_seen = BEIJING_TIMESTAMP(),
            seen_count = "节点库".seen_count + 1
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.create_function("BEIJING_TIMESTAMP", 0, beijing_timestamp)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS "节点库" (
                uri TEXT PRIMARY KEY,
                protocol TEXT NOT NULL,
                repo TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                encoding TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                seen_count INTEGER NOT NULL DEFAULT 1,
                validation_status TEXT NOT NULL DEFAULT '未验证',
                validation_reason TEXT NOT NULL DEFAULT '',
                validation_seconds REAL NOT NULL DEFAULT 0,
                proxy_ips TEXT NOT NULL DEFAULT '',
                last_validated TEXT,
                validation_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS "节点库_协议" ON "节点库" (protocol);

            CREATE TABLE IF NOT EXISTS "有效节点" (
                uri TEXT PRIMARY KEY,
                protocol TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                seconds REAL NOT NULL DEFAULT 0,
                proxy_ips TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                node_fingerprint TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'validator',
                manual_added INTEGER NOT NULL DEFAULT 0,
                manual_disabled INTEGER NOT NULL DEFAULT 0,
                manual_note TEXT NOT NULL DEFAULT '',
                disabled_at TEXT,
                disabled_reason TEXT NOT NULL DEFAULT '',
                cf_candidate INTEGER NOT NULL DEFAULT 0,
                first_validated TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_validated TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                validation_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS "有效节点_协议" ON "有效节点" (protocol);
            CREATE TABLE IF NOT EXISTS manual_blocked_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_fingerprint TEXT NOT NULL UNIQUE,
                uri_hash TEXT NOT NULL DEFAULT '',
                protocol TEXT NOT NULL DEFAULT '',
                server TEXT NOT NULL DEFAULT '',
                port TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS idx_manual_blocked_nodes_protocol ON manual_blocked_nodes (protocol, server, port);

            CREATE TABLE IF NOT EXISTS "无效节点" (
                uri TEXT PRIMARY KEY,
                protocol TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                seconds REAL NOT NULL DEFAULT 0,
                proxy_ips TEXT NOT NULL DEFAULT '',
                first_validated TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_validated TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                validation_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS "无效节点_协议" ON "无效节点" (protocol);

            CREATE TABLE IF NOT EXISTS "系统统计" (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS "采集仓库" (
                repo TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "采集来源画像" (
                repo TEXT NOT NULL,
                source TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                node_count INTEGER NOT NULL DEFAULT 0,
                last_nodes INTEGER NOT NULL DEFAULT 0,
                last_success TEXT,
                last_failure TEXT,
                valid_count INTEGER NOT NULL DEFAULT 0,
                invalid_count INTEGER NOT NULL DEFAULT 0,
                asia_valid_count INTEGER NOT NULL DEFAULT 0,
                valid_seconds_total REAL NOT NULL DEFAULT 0,
                consecutive_invalid_count INTEGER NOT NULL DEFAULT 0,
                cooldown_until TEXT,
                last_failure_category TEXT NOT NULL DEFAULT '',
                last_valid TEXT,
                last_invalid TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                PRIMARY KEY (repo, source)
            );

            CREATE TABLE IF NOT EXISTS "自动控制配置" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "节点处理配置" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "订阅转换配置" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "订阅转换日志" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                input_mode TEXT NOT NULL,
                input_type TEXT NOT NULL DEFAULT 'auto',
                node_count INTEGER NOT NULL DEFAULT 0,
                input_bytes INTEGER NOT NULL DEFAULT 0,
                output_bytes INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS "订阅转换日志_时间" ON "订阅转换日志" (created_at);

            CREATE TABLE IF NOT EXISTS subscription_conversion_cache (
                cache_key TEXT PRIMARY KEY,
                claim_code_version TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                node_hash TEXT NOT NULL,
                input_mode TEXT NOT NULL,
                input_type TEXT NOT NULL,
                export_limit INTEGER NOT NULL DEFAULT 100,
                prefer_asia INTEGER NOT NULL DEFAULT 1,
                backend_url TEXT NOT NULL DEFAULT '',
                profile_name TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                output_bytes INTEGER NOT NULL DEFAULT 0,
                hit_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_accessed_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS idx_subscription_conversion_cache_version ON subscription_conversion_cache (claim_code_version, target_id);
            CREATE INDEX IF NOT EXISTS idx_subscription_conversion_cache_access ON subscription_conversion_cache (last_accessed_at);

            CREATE TABLE IF NOT EXISTS premium_subscription_pool (
                uri TEXT PRIMARY KEY,
                score REAL NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                selected_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS idx_premium_subscription_pool_score ON premium_subscription_pool (score DESC, updated_at DESC);

            CREATE TABLE IF NOT EXISTS publish_subscription_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uri TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '',
                protocol TEXT NOT NULL DEFAULT '',
                server TEXT NOT NULL DEFAULT '',
                port TEXT NOT NULL DEFAULT '',
                source_pool TEXT NOT NULL DEFAULT 'premium_subscription_pool',
                manual_status TEXT NOT NULL DEFAULT 'publishable',
                publish_enabled INTEGER NOT NULL DEFAULT 1,
                manual_note TEXT NOT NULL DEFAULT '',
                last_checked_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS idx_publish_subscription_pool_status ON publish_subscription_pool (publish_enabled, manual_status, updated_at);

            CREATE TABLE IF NOT EXISTS "后台用户" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS "后台会话" (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES "后台用户"(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS "后台会话_用户" ON "后台会话" (user_id);
            CREATE INDEX IF NOT EXISTS "后台会话_过期" ON "后台会话" (expires_at);

            CREATE TABLE IF NOT EXISTS "订阅链接" (
                token TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                mode TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                claim_code_version TEXT NOT NULL DEFAULT '',
                max_uses INTEGER,
                export_limit INTEGER NOT NULL DEFAULT 100,
                used_count INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                rename_template TEXT NOT NULL DEFAULT '',
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_used_at TEXT,
                last_used_ip TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS "订阅链接_状态" ON "订阅链接" (enabled, mode, expires_at);
            CREATE INDEX IF NOT EXISTS "订阅链接_口令版本" ON "订阅链接" (claim_code_version, enabled);

            CREATE TABLE IF NOT EXISTS "Bot配置" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "Bot验证任务" (
                token TEXT PRIMARY KEY,
                telegram_user_id TEXT NOT NULL,
                telegram_chat_id TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待验证',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                expires_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS "Bot验证任务_用户" ON "Bot验证任务" (telegram_user_id, created_at);

            CREATE TABLE IF NOT EXISTS "Bot消息日志" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id TEXT NOT NULL DEFAULT '',
                telegram_chat_id TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS "Bot消息日志_时间" ON "Bot消息日志" (created_at);

            CREATE TABLE IF NOT EXISTS "领取口令配置" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "领取记录" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_date TEXT NOT NULL,
                client_key TEXT NOT NULL,
                version TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS "领取记录_每日客户端" ON "领取记录" (claim_date, client_key, version, status);

            CREATE TABLE IF NOT EXISTS "订阅访问日志" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                access_date TEXT NOT NULL,
                token TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                ip_hash TEXT NOT NULL DEFAULT '',
                user_agent_hash TEXT NOT NULL DEFAULT '',
                node_count INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT '',
                export_count INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS "订阅访问日志_时间" ON "订阅访问日志" (created_at);
            CREATE INDEX IF NOT EXISTS "订阅访问日志_日期订阅" ON "订阅访问日志" (access_date, token, status);

            CREATE TABLE IF NOT EXISTS "订阅访问汇总" (
                access_date TEXT NOT NULL,
                token TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                node_count INTEGER NOT NULL DEFAULT 0,
                latency_total_ms INTEGER NOT NULL DEFAULT 0,
                latency_max_ms INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                PRIMARY KEY (access_date, token, status)
            );

            CREATE TABLE IF NOT EXISTS "系统维护配置" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "系统维护记录" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reason TEXT NOT NULL,
                deleted_rows INTEGER NOT NULL DEFAULT 0,
                details TEXT NOT NULL DEFAULT '',
                database_bytes_before INTEGER NOT NULL DEFAULT 0,
                database_bytes_after INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS "系统维护记录_时间" ON "系统维护记录" (created_at);
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_ops_stats (
                stat_date TEXT NOT NULL,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                total_value INTEGER NOT NULL DEFAULT 0,
                max_value INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                PRIMARY KEY (stat_date, category, name)
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_ops_stats_date ON daily_ops_stats (stat_date, category)"
        )
        self._add_missing_columns()
        self._migrate_beijing_timestamps()
        self._migrate_long_run_defaults()
        self._migrate_quality_pool_defaults()
        self._migrate_stale_unvalidated_default()
        self.connection.commit()

    def _add_missing_columns(self) -> None:
        columns = {row[1] for row in self.connection.execute('PRAGMA table_info("节点库")')}
        migrations = {
            "validation_status": "TEXT NOT NULL DEFAULT '未验证'",
            "validation_reason": "TEXT NOT NULL DEFAULT ''",
            "validation_seconds": "REAL NOT NULL DEFAULT 0",
            "proxy_ips": "TEXT NOT NULL DEFAULT ''",
            "last_validated": "TEXT",
            "validation_count": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in migrations.items():
            if name not in columns:
                self.connection.execute('ALTER TABLE "节点库" ADD COLUMN "' + name + '" ' + declaration)
        valid_columns = {row[1] for row in self.connection.execute('PRAGMA table_info("有效节点")')}
        valid_migrations = {
            "country": 'TEXT NOT NULL DEFAULT ""',
            "node_fingerprint": 'TEXT NOT NULL DEFAULT ""',
            "source_type": "TEXT NOT NULL DEFAULT 'validator'",
            "manual_added": "INTEGER NOT NULL DEFAULT 0",
            "manual_disabled": "INTEGER NOT NULL DEFAULT 0",
            "manual_note": 'TEXT NOT NULL DEFAULT ""',
            "disabled_at": "TEXT",
            "disabled_reason": 'TEXT NOT NULL DEFAULT ""',
            "cf_candidate": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in valid_migrations.items():
            if name not in valid_columns:
                self.connection.execute('ALTER TABLE "有效节点" ADD COLUMN "' + name + '" ' + declaration)
        self.connection.execute('CREATE INDEX IF NOT EXISTS idx_valid_nodes_fingerprint ON "有效节点" (node_fingerprint)')
        self.connection.execute('CREATE INDEX IF NOT EXISTS idx_valid_nodes_manual_disabled ON "有效节点" (manual_disabled)')
        subscription_columns = {row[1] for row in self.connection.execute('PRAGMA table_info("订阅链接")')}
        if "export_limit" not in subscription_columns:
            self.connection.execute('ALTER TABLE "订阅链接" ADD COLUMN "export_limit" INTEGER NOT NULL DEFAULT 100')
        if "claim_code_version" not in subscription_columns:
            self.connection.execute('ALTER TABLE "订阅链接" ADD COLUMN "claim_code_version" TEXT NOT NULL DEFAULT ""')
        access_columns = {row[1] for row in self.connection.execute('PRAGMA table_info("订阅访问日志")')}
        if "source" not in access_columns:
            self.connection.execute('ALTER TABLE "订阅访问日志" ADD COLUMN "source" TEXT NOT NULL DEFAULT ""')
        if "export_count" not in access_columns:
            self.connection.execute('ALTER TABLE "订阅访问日志" ADD COLUMN "export_count" INTEGER NOT NULL DEFAULT 0')
        source_profile_columns = {row[1] for row in self.connection.execute('PRAGMA table_info("采集来源画像")')}
        source_profile_migrations = {
            "valid_count": "INTEGER NOT NULL DEFAULT 0",
            "invalid_count": "INTEGER NOT NULL DEFAULT 0",
            "asia_valid_count": "INTEGER NOT NULL DEFAULT 0",
            "valid_seconds_total": "REAL NOT NULL DEFAULT 0",
            "consecutive_invalid_count": "INTEGER NOT NULL DEFAULT 0",
            "cooldown_until": "TEXT",
            "last_failure_category": "TEXT NOT NULL DEFAULT ''",
            "last_valid": "TEXT",
            "last_invalid": "TEXT",
        }
        for name, declaration in source_profile_migrations.items():
            if name not in source_profile_columns:
                self.connection.execute('ALTER TABLE "采集来源画像" ADD COLUMN "' + name + '" ' + declaration)
        self.connection.execute('DELETE FROM "自动控制配置" WHERE key = "validator_limit"')

    def _migrate_long_run_defaults(self) -> None:
        key = "long_run_defaults_v2"
        if self.counter(key):
            return
        updates = {
            "bot_log_max_rows": ("10000", "5000"),
            "subscription_access_max_rows": ("20000", "10000"),
            "maintenance_record_days": ("180", "30"),
            "acceptance_report_max_files": ("300", "120"),
        }
        for config_key, (old_value, new_value) in updates.items():
            row = self.connection.execute(
                'SELECT value FROM "系统维护配置" WHERE key = ?',
                (config_key,),
            ).fetchone()
            if row and str(row[0]) == old_value:
                self.connection.execute(
                    'UPDATE "系统维护配置" SET value = ?, updated_at = BEIJING_TIMESTAMP() WHERE key = ?',
                    (new_value, config_key),
                )
        self.connection.execute(
            """
            INSERT INTO "系统统计" (key, value) VALUES (?, 1)
            ON CONFLICT(key) DO UPDATE SET value = 1
            """,
            (key,),
        )

    def _migrate_quality_pool_defaults(self) -> None:
        key = "quality_pool_defaults_v1"
        if self.counter(key):
            return
        table_updates = (
            ("自动控制配置", {
                "valid_low_watermark": ("20", "1000"),
                "collect_insert_target": ("200", "20000"),
                "validate_valid_target": ("50", "200"),
            }),
            ("订阅转换配置", {
                "export_limit": ("100", str(DEFAULT_SUBSCRIPTION_TARGET)),
            }),
            ("Bot配置", {
                "subscription_export_limit": ("100", str(DEFAULT_SUBSCRIPTION_TARGET)),
            }),
        )
        for table, updates in table_updates:
            for config_key, (old_value, new_value) in updates.items():
                row = self.connection.execute(
                    'SELECT value FROM "' + table + '" WHERE key = ?',
                    (config_key,),
                ).fetchone()
                if row and str(row[0]) == old_value:
                    self.connection.execute(
                        'UPDATE "' + table + '" SET value = ?, updated_at = BEIJING_TIMESTAMP() WHERE key = ?',
                        (new_value, config_key),
                    )
        self.connection.execute(
            """
            INSERT INTO "系统统计" (key, value) VALUES (?, 1)
            ON CONFLICT(key) DO UPDATE SET value = 1
            """,
            (key,),
        )

    def _migrate_stale_unvalidated_default(self) -> None:
        key = "stale_unvalidated_default_v1"
        if self.counter(key):
            return
        maintenance_table = "\u7cfb\u7edf\u7ef4\u62a4\u914d\u7f6e"
        stats_table = "\u7cfb\u7edf\u7edf\u8ba1"
        row = self.connection.execute(
            'SELECT value FROM "' + maintenance_table + '" WHERE key = ?',
            ("stale_unvalidated_node_days",),
        ).fetchone()
        if row and str(row[0]) == "3":
            self.connection.execute(
                'UPDATE "' + maintenance_table + '" SET value = ?, updated_at = BEIJING_TIMESTAMP() WHERE key = ?',
                ("2", "stale_unvalidated_node_days"),
            )
        self.connection.execute(
            'INSERT INTO "' + stats_table + '" (key, value) VALUES (?, 1) '
            'ON CONFLICT(key) DO UPDATE SET value = 1',
            (key,),
        )

    def _migrate_beijing_timestamps(self) -> None:
        key = "beijing_timezone_migration_v1"
        if self.counter(key):
            return
        migrations = {
            "节点库": ("first_seen", "last_seen", "last_validated"),
            "有效节点": ("first_validated", "last_validated"),
            "采集仓库": ("created_at", "updated_at"),
            "采集来源画像": ("last_success", "last_failure", "updated_at"),
            "自动控制配置": ("updated_at",),
            "节点处理配置": ("updated_at",),
            "订阅转换配置": ("updated_at",),
            "订阅转换日志": ("created_at",),
            "后台用户": ("created_at", "updated_at", "last_login_at"),
            "后台会话": ("created_at", "expires_at", "last_seen_at"),
            "订阅链接": ("created_at", "updated_at", "last_used_at"),
            "Bot配置": ("updated_at",),
            "Bot验证任务": ("created_at", "expires_at", "completed_at"),
            "Bot消息日志": ("created_at",),
            "领取口令配置": ("updated_at",),
            "领取记录": ("created_at",),
            "订阅访问日志": ("created_at",),
            "订阅访问汇总": ("updated_at",),
            "系统维护配置": ("updated_at",),
            "系统维护记录": ("created_at",),
        }
        for table, columns in migrations.items():
            for column in columns:
                self.connection.execute(
                    'UPDATE "' + table + '" SET "' + column + '" = datetime("' + column + '", \'+8 hours\') '
                    'WHERE "' + column + '" IS NOT NULL AND "' + column + '" != ""'
                )
        self.connection.execute(
            """
            INSERT INTO "系统统计" (key, value) VALUES (?, 1)
            ON CONFLICT(key) DO UPDATE SET value = 1
            """,
            (key,),
        )
        self.connection.commit()

    def upsert_node(self, uri: str, repo: str = "", source: str = "", encoding: str = "") -> None:
        self.upsert_nodes([(uri, repo, source, encoding)])

    def upsert_nodes(self, nodes: Iterable[Tuple[str, str, str, str]]) -> int:
        return self.upsert_nodes_with_stats(nodes)["duplicates"]

    def upsert_nodes_with_stats(self, nodes: Iterable[Tuple[str, str, str, str]]) -> Dict[str, object]:
        rows = [(uri, protocol_of(uri), repo, source, encoding) for uri, repo, source, encoding in nodes]
        if not rows:
            return {"parsed": 0, "inserted": 0, "duplicates": 0, "total": self.count("节点库"), "inserted_uris": []}
        unique_rows = {}
        for row in rows:
            unique_rows[row[0]] = row
        existing_pending = set()
        existing_verified = set()
        uris = list(unique_rows)
        for start in range(0, len(uris), 500):
            chunk = uris[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            existing_pending.update(
                row[0] for row in self.connection.execute(
                    'SELECT uri FROM "节点库" WHERE uri IN (' + placeholders + ')',
                    chunk,
                )
            )
            existing_verified.update(
                row[0] for row in self.connection.execute(
                    'SELECT uri FROM "有效节点" WHERE uri IN (' + placeholders + ')',
                    chunk,
                )
            )
        existing = existing_pending | existing_verified
        duplicate_count = len(rows) - len(unique_rows) + len(existing)
        blocked_uris = {uri for uri in unique_rows if self.is_node_blocked(uri)}
        upsert_rows = [row for row in unique_rows.values() if row[0] not in existing_verified and row[0] not in blocked_uris]
        self.connection.executemany(self.NODE_UPSERT, upsert_rows)
        if duplicate_count:
            self.connection.execute(
                """
                INSERT INTO "系统统计" (key, value) VALUES ('duplicate_filtered', ?)
                ON CONFLICT(key) DO UPDATE SET value = value + excluded.value
                """,
                (duplicate_count,),
            )
        self.connection.commit()
        return {
            "parsed": len(rows),
            "inserted": len(unique_rows) - len(existing) - len(blocked_uris),
            "duplicates": duplicate_count + len(blocked_uris),
            "total": self.count("节点库"),
            "inserted_uris": [uri for uri in unique_rows if uri not in existing and uri not in blocked_uris],
        }

    def is_node_blocked(self, uri: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM manual_blocked_nodes WHERE node_fingerprint = ?",
            (node_fingerprint(uri),),
        ).fetchone()
        return bool(row)

    def block_node(self, uri: str, reason: str = "") -> Dict[str, object]:
        meta = uri_metadata(uri)
        fingerprint = node_fingerprint(uri)
        self.connection.execute(
            """
            INSERT INTO manual_blocked_nodes (
                node_fingerprint, uri_hash, protocol, server, port, reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            ON CONFLICT(node_fingerprint) DO UPDATE SET
                uri_hash = excluded.uri_hash,
                protocol = excluded.protocol,
                server = excluded.server,
                port = excluded.port,
                reason = excluded.reason,
                updated_at = BEIJING_TIMESTAMP()
            """,
            (
                fingerprint,
                uri_hash(uri),
                str(meta.get("protocol") or protocol_of(uri)),
                str(meta.get("server") or ""),
                str(meta.get("port") or ""),
                str(reason or "")[:500],
            ),
        )
        return {"node_fingerprint": fingerprint, **meta}

    def record_validation(
        self,
        uri: str,
        status: str,
        reason: str,
        seconds: float,
        proxy_ips: Optional[str] = None,
        country: str = "",
    ) -> None:
        if status not in ("有效", "无效"):
            raise ValueError("unknown validation status: " + status)
        source_row = self.connection.execute(
            'SELECT repo, source FROM "节点库" WHERE uri = ?',
            (uri,),
        ).fetchone()
        fingerprint = node_fingerprint(uri)
        meta = uri_metadata(uri)
        source_repo = source_row[0] if source_row else ""
        source_path = source_row[1] if source_row else ""
        if status == "无效":
            failure_category = classify_validation_failure(reason)
            if source_row:
                self._record_source_validation(source_row[0], source_row[1], False, seconds, country, failure_category)
            self._increment_daily_ops_stat("validation", "invalid", 1, int(max(float(seconds or 0), 0) * 1000), int(max(float(seconds or 0), 0) * 1000))
            self._increment_daily_ops_stat("validation_failure", failure_category, 1)
            self.connection.execute(
                """
                INSERT INTO "系统统计" (key, value) VALUES ('invalid_nodes_total', 1)
                ON CONFLICT(key) DO UPDATE SET value = value + 1
                """
            )
            self.connection.execute('DELETE FROM "有效节点" WHERE uri = ?', (uri,))
            self.connection.execute('DELETE FROM "无效节点" WHERE uri = ?', (uri,))
            self.connection.execute('DELETE FROM "节点库" WHERE uri = ?', (uri,))
            self.connection.execute("DELETE FROM premium_subscription_pool WHERE uri = ?", (uri,))
            self.connection.execute("DELETE FROM publish_subscription_pool WHERE uri = ?", (uri,))
            self.connection.commit()
            return
        if self.is_node_blocked(uri):
            self.connection.execute('DELETE FROM "节点库" WHERE uri = ?', (uri,))
            self.connection.execute('DELETE FROM "有效节点" WHERE uri = ?', (uri,))
            self.connection.execute("DELETE FROM premium_subscription_pool WHERE uri = ?", (uri,))
            self.connection.execute("DELETE FROM publish_subscription_pool WHERE uri = ?", (uri,))
            self.connection.commit()
            return
        if source_row:
            self._record_source_validation(source_row[0], source_row[1], True, seconds, country)
        self._increment_daily_ops_stat("validation", "valid", 1, int(max(float(seconds or 0), 0) * 1000), int(max(float(seconds or 0), 0) * 1000))
        self.connection.execute('DELETE FROM "无效节点" WHERE uri = ?', (uri,))
        self.connection.execute(
            """
            INSERT INTO "有效节点" (
                uri, protocol, reason, seconds, proxy_ips, country,
                node_fingerprint, source_type, manual_added, manual_disabled,
                manual_note, disabled_at, disabled_reason, cf_candidate,
                first_validated, last_validated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'validator', 0, 0, '', NULL, '', ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            ON CONFLICT(uri) DO UPDATE SET
                reason = excluded.reason,
                seconds = excluded.seconds,
                proxy_ips = excluded.proxy_ips,
                country = excluded.country,
                node_fingerprint = excluded.node_fingerprint,
                source_type = CASE WHEN "有效节点".manual_added = 1 THEN "有效节点".source_type ELSE excluded.source_type END,
                cf_candidate = excluded.cf_candidate,
                last_validated = BEIJING_TIMESTAMP(),
                validation_count = "有效节点".validation_count + 1
            """,
            (
                uri,
                protocol_of(uri),
                reason,
                seconds,
                proxy_ips or "",
                country,
                fingerprint,
                1 if is_cf_candidate_uri(uri, source_repo, source_path) else 0,
            ),
        )
        self.connection.execute('DELETE FROM "节点库" WHERE uri = ?', (uri,))
        self.connection.commit()

    def upsert_valid_node(self, uri: str, reason: str, seconds: float, proxy_ips: Optional[str] = None, country: str = "") -> None:
        self.record_validation(uri, "有效", reason, seconds, proxy_ips, country)

    def validate_manual_node_uri(self, uri: str) -> Tuple[bool, str, Dict[str, object]]:
        uri = str(uri or "").strip()
        if not uri:
            return False, "空行", {}
        protocol = protocol_of(uri)
        if protocol not in {"vmess", "vless", "trojan", "ss", "ssr"}:
            return False, "不支持的协议", {"protocol": protocol}
        meta = uri_metadata(uri)
        if not meta.get("server"):
            return False, "缺少 server", meta
        if not meta.get("port"):
            return False, "缺少 port", meta
        if not meta.get("uuid_present"):
            return False, "缺少 uuid/password", meta
        if self.is_node_blocked(uri):
            return False, "节点已被手动禁用", meta
        return True, "ok", meta

    def import_manual_valid_nodes(self, text: str, note: str = "") -> Dict[str, object]:
        raw_lines = [line.strip() for line in str(text or "").splitlines()]
        lines = [line for line in raw_lines if line and not line.lstrip().startswith("#")]
        added = []
        duplicates = []
        invalid = []
        seen_fingerprints = set()
        for line in lines:
            ok, reason, meta = self.validate_manual_node_uri(line)
            fingerprint = node_fingerprint(line)
            if not ok:
                invalid.append({"uri": line, "reason": reason})
                continue
            if fingerprint in seen_fingerprints:
                duplicates.append({"uri": line, "reason": "本次导入重复"})
                continue
            seen_fingerprints.add(fingerprint)
            exists = self.connection.execute(
                'SELECT uri FROM "有效节点" WHERE node_fingerprint = ? AND manual_disabled = 0',
                (fingerprint,),
            ).fetchone()
            if exists:
                duplicates.append({"uri": line, "reason": "有效节点库已存在"})
                continue
            self.connection.execute(
                """
                INSERT INTO "有效节点" (
                    uri, protocol, reason, seconds, proxy_ips, country,
                    node_fingerprint, source_type, manual_added, manual_disabled,
                    manual_note, disabled_at, disabled_reason, cf_candidate,
                    first_validated, last_validated, validation_count
                ) VALUES (?, ?, ?, 0, '', '', ?, 'manual', 1, 0, ?, NULL, '', ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP(), 1)
                ON CONFLICT(uri) DO UPDATE SET
                    reason = excluded.reason,
                    node_fingerprint = excluded.node_fingerprint,
                    source_type = 'manual',
                    manual_added = 1,
                    manual_disabled = 0,
                    manual_note = excluded.manual_note,
                    disabled_at = NULL,
                    disabled_reason = '',
                    cf_candidate = excluded.cf_candidate,
                    last_validated = BEIJING_TIMESTAMP()
                """,
                (
                    line,
                    str(meta.get("protocol") or protocol_of(line)),
                    "manual_node_add",
                    fingerprint,
                    str(note or "")[:500],
                    1 if is_cf_candidate_uri(line) else 0,
                ),
            )
            added.append({
                "uri": line,
                "protocol": str(meta.get("protocol") or protocol_of(line)),
                "server": str(meta.get("server") or ""),
                "port": str(meta.get("port") or ""),
                "node_fingerprint": fingerprint,
            })
        self.connection.commit()
        return {
            "added_count": len(added),
            "duplicate_count": len(duplicates),
            "invalid_count": len(invalid),
            "added": added,
            "duplicates": duplicates,
            "invalid": invalid,
            "operator": "admin",
            "event": "manual_node_add",
        }

    def _remove_node_from_pools(self, uri: str) -> Dict[str, object]:
        premium = self.connection.execute("DELETE FROM premium_subscription_pool WHERE uri = ?", (uri,)).rowcount
        publish = self.connection.execute("DELETE FROM publish_subscription_pool WHERE uri = ?", (uri,)).rowcount
        cache = self.connection.execute("DELETE FROM subscription_conversion_cache").rowcount
        return {
            "removed_from_premium_pool": bool(premium),
            "removed_from_publish_pool": bool(publish),
            "conversion_cache_cleared": True,
            "cleared_conversion_cache_rows": int(cache or 0),
        }

    def disable_valid_node(self, uri: str, reason: str = "") -> Dict[str, object]:
        uri = str(uri or "").strip()
        row = self.connection.execute(
            'SELECT uri, protocol FROM "有效节点" WHERE uri = ?',
            (uri,),
        ).fetchone()
        if not row:
            raise ValueError("有效节点不存在")
        meta = self.block_node(uri, reason or "manual_node_disable")
        self.connection.execute(
            """
            UPDATE "有效节点"
            SET manual_disabled = 1,
                disabled_at = BEIJING_TIMESTAMP(),
                disabled_reason = ?,
                manual_note = CASE WHEN manual_note = '' THEN ? ELSE manual_note END
            WHERE uri = ?
            """,
            (str(reason or "manual_node_disable")[:500], str(reason or "manual_node_disable")[:500], uri),
        )
        details = self._remove_node_from_pools(uri)
        self.connection.commit()
        return {
            "event": "manual_node_disable",
            "uri": uri,
            "protocol": str(row[1]),
            "server": str(meta.get("server") or ""),
            "port": str(meta.get("port") or ""),
            **details,
        }

    def delete_valid_node(self, uri: str, reason: str = "") -> Dict[str, object]:
        uri = str(uri or "").strip()
        row = self.connection.execute(
            'SELECT uri, protocol FROM "有效节点" WHERE uri = ?',
            (uri,),
        ).fetchone()
        if not row:
            raise ValueError("有效节点不存在")
        meta = self.block_node(uri, reason or "manual_node_delete")
        deleted = self.connection.execute('DELETE FROM "有效节点" WHERE uri = ?', (uri,)).rowcount
        details = self._remove_node_from_pools(uri)
        self.connection.commit()
        return {
            "event": "manual_node_delete",
            "uri": uri,
            "deleted": bool(deleted),
            "protocol": str(row[1]),
            "server": str(meta.get("server") or ""),
            "port": str(meta.get("port") or ""),
            **details,
        }

    def remove_from_premium_pool(self, uri: str) -> Dict[str, object]:
        uri = str(uri or "").strip()
        removed = self.connection.execute("DELETE FROM premium_subscription_pool WHERE uri = ?", (uri,)).rowcount
        cache = self.connection.execute("DELETE FROM subscription_conversion_cache").rowcount
        self.connection.commit()
        return {
            "event": "manual_node_remove_premium",
            "uri": uri,
            "removed_from_premium_pool": bool(removed),
            "conversion_cache_cleared": True,
            "cleared_conversion_cache_rows": int(cache or 0),
        }

    def count(self, table: str) -> int:
        if table not in ("节点库", "有效节点", "无效节点"):
            raise ValueError("unknown table: " + table)
        return self.connection.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]

    def iter_nodes(self, protocols: Sequence[str] = (), revalidate: bool = False) -> Iterator[str]:
        clauses = []
        params = []
        if protocols:
            placeholders = ",".join("?" for _ in protocols)
            clauses.append("n.protocol IN (" + placeholders + ")")
            params.extend(protocol.lower() for protocol in protocols)
        if not revalidate:
            clauses.append("n.validation_status = '未验证'")
        sql = (
            'SELECT n.uri FROM "节点库" n '
            'LEFT JOIN "采集来源画像" p ON p.repo = n.repo AND p.source = n.source'
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += """
            ORDER BY
                CASE n.protocol
                    WHEN 'vless' THEN 0
                    WHEN 'vmess' THEN 1
                    WHEN 'trojan' THEN 2
                    WHEN 'ss' THEN 3
                    WHEN 'socks' THEN 4
                    WHEN 'socks5' THEN 4
                    ELSE 9
                END,
                CASE
                    WHEN p.cooldown_until IS NOT NULL AND p.cooldown_until > BEIJING_TIMESTAMP() THEN 1
                    ELSE 0
                END,
                (
                    COALESCE(p.valid_count, 0) * 200
                    + COALESCE(p.asia_valid_count, 0) * 60
                    + COALESCE(p.success_count, 0) * 10
                    + COALESCE(p.node_count, 0) / 10
                    - COALESCE(p.invalid_count, 0) * 5
                    - COALESCE(p.fail_count, 0) * 25
                ) DESC,
                n.seen_count DESC,
                n.last_seen DESC,
                n.rowid
        """
        rows = self.connection.execute(sql, params)
        for row in rows:
            yield row[0]

    def stats(self) -> Dict[str, object]:
        statuses = dict(self.connection.execute(
            'SELECT validation_status, COUNT(*) FROM "节点库" GROUP BY validation_status'
        ))
        pending_count = self.count("节点库")
        valid_count = self.connection.execute('SELECT COUNT(*) FROM "有效节点" WHERE manual_disabled = 0').fetchone()[0]
        invalid_count = self.count("无效节点")
        premium_count = self.connection.execute("SELECT COUNT(*) FROM premium_subscription_pool").fetchone()[0]
        publish_count = self.connection.execute(
            "SELECT COUNT(*) FROM publish_subscription_pool WHERE publish_enabled = 1 AND manual_status = 'publishable'"
        ).fetchone()[0]
        invalid_total = self.counter("invalid_nodes_total") + self.counter("invalid_nodes_pruned")
        if valid_count:
            statuses["有效"] = valid_count
        if invalid_count:
            statuses["无效"] = invalid_count
        protocols = dict(self.connection.execute(
            'SELECT protocol, COUNT(*) FROM "节点库" GROUP BY protocol ORDER BY COUNT(*) DESC'
        ))
        return {
            "total_nodes": pending_count,
            "pending_nodes": pending_count,
            "all_nodes": pending_count + valid_count + invalid_count,
            "asset_nodes": pending_count + valid_count + invalid_count,
            "current_inventory_nodes": pending_count + valid_count,
            "valid_nodes": valid_count,
            "invalid_nodes": invalid_count,
            "premium_nodes": premium_count,
            "publish_nodes": publish_count,
            "invalid_nodes_total": invalid_total,
            "historical_invalid_nodes": invalid_total,
            "duplicate_filtered": self.counter("duplicate_filtered"),
            "statuses": statuses,
            "protocols": protocols,
        }

    def clear_node_pool(self, scope: str) -> Dict[str, int]:
        scope = str(scope or "").strip().lower()
        if scope not in {"pending", "valid"}:
            raise ValueError("unsupported node pool scope")
        details: Dict[str, int] = {}
        if scope == "pending":
            cursor = self.connection.execute('DELETE FROM "节点库"')
            details["pending_nodes"] = int(cursor.rowcount or 0)
        if scope == "valid":
            cursor = self.connection.execute('DELETE FROM "有效节点"')
            details["valid_nodes"] = int(cursor.rowcount or 0)
            cursor = self.connection.execute("DELETE FROM premium_subscription_pool")
            details["premium_subscription_pool"] = int(cursor.rowcount or 0)
            cursor = self.connection.execute("DELETE FROM publish_subscription_pool")
            details["publish_subscription_pool"] = int(cursor.rowcount or 0)
            cursor = self.connection.execute("DELETE FROM subscription_conversion_cache")
            details["subscription_conversion_cache"] = int(cursor.rowcount or 0)
        self.connection.commit()
        return details

    def cleanup_stale_unvalidated_nodes(self, days: int = 2) -> Dict[str, int]:
        days = max(1, int(days or 3))
        threshold = "-" + str(days) + " days"
        stale_valid = [
            row[0] for row in self.connection.execute(
                'SELECT uri FROM "有效节点" WHERE last_validated < datetime(BEIJING_TIMESTAMP(), ?)',
                (threshold,),
            ).fetchall()
        ]
        stale_pending = [
            row[0] for row in self.connection.execute(
                """
                SELECT uri FROM "节点库"
                WHERE COALESCE(last_validated, first_seen, last_seen) < datetime(BEIJING_TIMESTAMP(), ?)
                """,
                (threshold,),
            ).fetchall()
        ]
        valid_deleted = 0
        premium_deleted = 0
        if stale_valid:
            placeholders = ",".join("?" for _ in stale_valid)
            cursor = self.connection.execute('DELETE FROM "有效节点" WHERE uri IN (' + placeholders + ')', stale_valid)
            valid_deleted = int(cursor.rowcount or 0)
            cursor = self.connection.execute("DELETE FROM premium_subscription_pool WHERE uri IN (" + placeholders + ")", stale_valid)
            premium_deleted = int(cursor.rowcount or 0)
        pending_deleted = 0
        if stale_pending:
            placeholders = ",".join("?" for _ in stale_pending)
            cursor = self.connection.execute('DELETE FROM "节点库" WHERE uri IN (' + placeholders + ')', stale_pending)
            pending_deleted = int(cursor.rowcount or 0)
        self.connection.commit()
        return {
            "有效节点_超过天数未验证": valid_deleted,
            "待验证节点_超过天数未验证": pending_deleted,
            "订阅候选池_同步删除": premium_deleted,
        }

    def counter(self, key: str) -> int:
        row = self.connection.execute('SELECT value FROM "系统统计" WHERE key = ?', (key,)).fetchone()
        return row[0] if row else 0

    def auto_config_defaults(self) -> Dict[str, object]:
        return {
            "enabled": False,
            "valid_low_watermark": 1000,
            "collect_insert_target": 20000,
            "validate_valid_target": 200,
            "check_interval_minutes": 5,
            "collector_workers": 5,
            "collector_depth": 8,
            "collector_delay": 1.0,
            "collector_jitter": 0.5,
            "collector_log_level": "detail",
            "validator_workers": 20,
            "validator_rounds": 1,
            "validator_timeout": 5,
            "recheck_enabled": False,
            "recheck_interval_minutes": 360,
            "recheck_limit": 50,
        }

    def auto_config(self) -> Dict[str, object]:
        config = self.auto_config_defaults()
        rows = dict(self.connection.execute('SELECT key, value FROM "自动控制配置"'))
        if "check_interval_minutes" not in rows and "check_interval" in rows:
            try:
                config["check_interval_minutes"] = max(1, int(float(rows["check_interval"])) // 60)
            except ValueError:
                pass
        for key, default in list(config.items()):
            if key not in rows:
                continue
            value = rows[key]
            if isinstance(default, bool):
                config[key] = value in ("1", "true", "True", "yes", "on")
            elif isinstance(default, int):
                try:
                    config[key] = int(float(value))
                except ValueError:
                    config[key] = default
            elif isinstance(default, float):
                try:
                    config[key] = float(value)
                except ValueError:
                    config[key] = default
            else:
                config[key] = value
        return config

    def update_auto_config(self, values: Dict[str, object]) -> Dict[str, object]:
        defaults = self.auto_config_defaults()
        cleaned: Dict[str, object] = {}
        for key, default in defaults.items():
            if key not in values:
                continue
            value = values[key]
            if isinstance(default, bool):
                cleaned[key] = bool(value)
            elif isinstance(default, int):
                cleaned[key] = int(value)
            elif isinstance(default, float):
                cleaned[key] = float(value)
            else:
                cleaned[key] = str(value)
        if cleaned:
            self.connection.executemany(
                """
                INSERT INTO "自动控制配置" (key, value, updated_at)
                VALUES (?, ?, BEIJING_TIMESTAMP())
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = BEIJING_TIMESTAMP()
                """,
                [(key, "1" if value is True else "0" if value is False else str(value)) for key, value in cleaned.items()],
            )
            self.connection.commit()
        return self.auto_config()

    def processing_config_defaults(self) -> Dict[str, str]:
        return {
            "rename_template": "{country_name} {protocol} {validated_date} #{index}",
        }

    def processing_config(self) -> Dict[str, str]:
        config = self.processing_config_defaults()
        rows = dict(self.connection.execute('SELECT key, value FROM "节点处理配置"'))
        for key in config:
            if key in rows:
                config[key] = rows[key]
        return config

    def update_processing_config(self, values: Dict[str, object]) -> Dict[str, str]:
        defaults = self.processing_config_defaults()
        cleaned = {
            key: str(values[key])
            for key in defaults
            if key in values
        }
        if cleaned:
            self.connection.executemany(
                """
                INSERT INTO "节点处理配置" (key, value, updated_at)
                VALUES (?, ?, BEIJING_TIMESTAMP())
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = BEIJING_TIMESTAMP()
                """,
                list(cleaned.items()),
            )
            self.connection.commit()
        return self.processing_config()

    def subscription_converter_defaults(self) -> Dict[str, object]:
        return {
            "backend_url": os.environ.get("HUAGE_SUB_STORE_URL", "http://127.0.0.1:3001"),
            "profile_name": os.environ.get("HUAGE_SUB_STORE_PROFILE", "sub"),
            "export_limit": DEFAULT_SUBSCRIPTION_TARGET,
            "prefer_asia": True,
        }

    def subscription_converter_config(self) -> Dict[str, object]:
        config = self.subscription_converter_defaults()
        rows = dict(self.connection.execute('SELECT key, value FROM "订阅转换配置"'))
        config.update({key: value for key, value in rows.items() if key in config})
        if not os.environ.get("HUAGE_SUB_STORE_URL") and config.get("backend_url") == "http://127.0.0.1:3000":
            config["backend_url"] = "http://127.0.0.1:3001"
        try:
            config["export_limit"] = normalize_subscription_limit(config["export_limit"])
        except (TypeError, ValueError):
            config["export_limit"] = DEFAULT_SUBSCRIPTION_TARGET
        config["prefer_asia"] = str(config["prefer_asia"]).lower() in ("1", "true", "yes", "on")
        return config

    def update_subscription_converter_config(self, values: Dict[str, object]) -> Dict[str, object]:
        defaults = self.subscription_converter_defaults()
        cleaned = {}
        for key in defaults:
            if key not in values:
                continue
            value = values[key]
            if key == "export_limit":
                value = str(normalize_subscription_limit(value))
            elif key == "prefer_asia":
                value = "1" if value is True or str(value).lower() in ("1", "true", "yes", "on") else "0"
            else:
                value = str(value).strip()
                if not value:
                    value = str(defaults[key])
            cleaned[key] = value
        if cleaned:
            self.connection.executemany(
                """
                INSERT INTO "订阅转换配置" (key, value, updated_at)
                VALUES (?, ?, BEIJING_TIMESTAMP())
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = BEIJING_TIMESTAMP()
                """,
                [(key, str(value)) for key, value in cleaned.items()],
            )
            self.connection.commit()
        return self.subscription_converter_config()

    def record_subscription_converter_log(
        self,
        target_id: str,
        target_name: str,
        input_mode: str,
        input_type: str,
        node_count: int,
        input_bytes: int,
        output_bytes: int,
        status: str,
        message: str = "",
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO "订阅转换日志" (
                target_id, target_name, input_mode, input_type, node_count,
                input_bytes, output_bytes, status, message, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP())
            """,
            (
                str(target_id)[:80],
                str(target_name)[:120],
                str(input_mode)[:40],
                str(input_type)[:40],
                max(0, int(node_count or 0)),
                max(0, int(input_bytes or 0)),
                max(0, int(output_bytes or 0)),
                str(status)[:40],
                str(message)[:500],
            ),
        )
        self.connection.commit()

    def subscription_converter_logs(self, limit: int = 50) -> List[dict]:
        limit = max(1, min(int(limit or 50), 100))
        rows = self.connection.execute(
            """
            SELECT id, target_id, target_name, input_mode, input_type, node_count,
                   input_bytes, output_bytes, status, message, created_at
            FROM "订阅转换日志"
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        keys = (
            "id", "target_id", "target_name", "input_mode", "input_type", "node_count",
            "input_bytes", "output_bytes", "status", "message", "created_at",
        )
        return [dict(zip(keys, row)) for row in rows]

    def subscription_conversion_cache_get(self, cache_key: str) -> Optional[Dict[str, object]]:
        row = self.connection.execute(
            """
            SELECT cache_key, claim_code_version, target_id, target_name, node_hash,
                   input_mode, input_type, export_limit, prefer_asia, backend_url,
                   profile_name, content, output_bytes, hit_count, created_at,
                   updated_at, last_accessed_at
            FROM subscription_conversion_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        self.connection.execute(
            """
            UPDATE subscription_conversion_cache
            SET hit_count = hit_count + 1,
                last_accessed_at = BEIJING_TIMESTAMP()
            WHERE cache_key = ?
            """,
            (cache_key,),
        )
        self.connection.commit()
        keys = (
            "cache_key", "claim_code_version", "target_id", "target_name", "node_hash",
            "input_mode", "input_type", "export_limit", "prefer_asia", "backend_url",
            "profile_name", "content", "output_bytes", "hit_count", "created_at",
            "updated_at", "last_accessed_at",
        )
        return dict(zip(keys, row))

    def subscription_conversion_cache_put(self, values: Dict[str, object]) -> Dict[str, object]:
        self.connection.execute(
            """
            INSERT INTO subscription_conversion_cache (
                cache_key, claim_code_version, target_id, target_name, node_hash,
                input_mode, input_type, export_limit, prefer_asia, backend_url,
                profile_name, content, output_bytes, hit_count, created_at,
                updated_at, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            ON CONFLICT(cache_key) DO UPDATE SET
                claim_code_version = excluded.claim_code_version,
                target_id = excluded.target_id,
                target_name = excluded.target_name,
                node_hash = excluded.node_hash,
                input_mode = excluded.input_mode,
                input_type = excluded.input_type,
                export_limit = excluded.export_limit,
                prefer_asia = excluded.prefer_asia,
                backend_url = excluded.backend_url,
                profile_name = excluded.profile_name,
                content = excluded.content,
                output_bytes = excluded.output_bytes,
                updated_at = BEIJING_TIMESTAMP(),
                last_accessed_at = BEIJING_TIMESTAMP()
            """,
            (
                str(values["cache_key"]),
                str(values["claim_code_version"]),
                str(values["target_id"]),
                str(values["target_name"]),
                str(values["node_hash"]),
                str(values["input_mode"]),
                str(values["input_type"]),
                int(values.get("export_limit") or 100),
                1 if values.get("prefer_asia") else 0,
                str(values.get("backend_url") or ""),
                str(values.get("profile_name") or ""),
                str(values.get("content") or ""),
                int(values.get("output_bytes") or 0),
            ),
        )
        self.connection.commit()
        return dict(values)

    def subscription_conversion_cache_stats(self) -> Dict[str, object]:
        row = self.connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(output_bytes), 0), COALESCE(SUM(hit_count), 0),
                   MAX(last_accessed_at)
            FROM subscription_conversion_cache
            """
        ).fetchone()
        targets = self.connection.execute(
            """
            SELECT target_id, COUNT(*) AS count, COALESCE(SUM(hit_count), 0) AS hits,
                   COALESCE(SUM(output_bytes), 0) AS bytes
            FROM subscription_conversion_cache
            GROUP BY target_id
            ORDER BY hits DESC, count DESC
            """
        ).fetchall()
        return {
            "rows": int(row[0] or 0) if row else 0,
            "bytes": int(row[1] or 0) if row else 0,
            "hits": int(row[2] or 0) if row else 0,
            "last_accessed_at": row[3] if row else None,
            "targets": [
                {"target_id": item[0], "count": int(item[1] or 0), "hits": int(item[2] or 0), "bytes": int(item[3] or 0)}
                for item in targets
            ],
        }

    def clear_subscription_conversion_cache(self) -> int:
        cursor = self.connection.execute("DELETE FROM subscription_conversion_cache")
        self.connection.commit()
        return int(cursor.rowcount or 0)

    def collector_repos(self, defaults: Sequence[str] = ()) -> List[str]:
        total = self.connection.execute('SELECT COUNT(*) FROM "采集仓库"').fetchone()[0]
        rows = [
            row[0] for row in self.connection.execute(
                'SELECT repo FROM "采集仓库" WHERE enabled = 1 ORDER BY sort_order, repo'
            )
        ]
        if rows or total:
            return rows
        return list(defaults)

    def collector_repo_items(self, defaults: Sequence[str] = ()) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT repo, enabled, sort_order, created_at, updated_at
            FROM "采集仓库"
            ORDER BY sort_order, repo
            """
        )
        items = [
            {
                "repo": row[0],
                "enabled": bool(row[1]),
                "sort_order": row[2],
                "created_at": row[3],
                "updated_at": row[4],
            }
            for row in rows
        ]
        if items:
            return items
        return [
            {
                "repo": repo,
                "enabled": True,
                "sort_order": index,
                "created_at": "",
                "updated_at": "",
            }
            for index, repo in enumerate(defaults)
        ]

    def replace_collector_repos(self, repos: Sequence[str]) -> None:
        existing_enabled = dict(self.connection.execute('SELECT repo, enabled FROM "采集仓库"'))
        self.connection.execute('DELETE FROM "采集仓库"')
        self.connection.executemany(
            """
            INSERT INTO "采集仓库" (repo, enabled, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            """,
            [(repo, 1 if existing_enabled.get(repo, 1) else 0, index) for index, repo in enumerate(repos)],
        )
        self.connection.commit()

    def set_collector_repo_enabled(self, repo: str, enabled: bool) -> Dict[str, object]:
        row = self.connection.execute('SELECT sort_order FROM "采集仓库" WHERE repo = ?', (repo,)).fetchone()
        if row:
            self.connection.execute(
                'UPDATE "采集仓库" SET enabled = ?, updated_at = BEIJING_TIMESTAMP() WHERE repo = ?',
                (1 if enabled else 0, repo),
            )
        else:
            next_order = self.connection.execute('SELECT COALESCE(MAX(sort_order), -1) + 1 FROM "采集仓库"').fetchone()[0]
            self.connection.execute(
                """
                INSERT INTO "采集仓库" (repo, enabled, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
                """,
                (repo, 1 if enabled else 0, next_order),
            )
        self.connection.commit()
        return next(item for item in self.collector_repo_items() if item["repo"] == repo)

    def record_source_result(self, repo: str, source: str, nodes: int, success: bool) -> None:
        if not repo or not source:
            return
        if success:
            self.connection.execute(
                """
                INSERT INTO "采集来源画像" (repo, source, success_count, node_count, last_nodes, last_success, updated_at)
                VALUES (?, ?, 1, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
                ON CONFLICT(repo, source) DO UPDATE SET
                    success_count = success_count + 1,
                    node_count = node_count + excluded.node_count,
                    last_nodes = excluded.last_nodes,
                    last_success = BEIJING_TIMESTAMP(),
                    updated_at = BEIJING_TIMESTAMP()
                """,
                (repo, source, nodes, nodes),
            )
        else:
            self.connection.execute(
                """
                INSERT INTO "采集来源画像" (repo, source, fail_count, last_failure, updated_at)
                VALUES (?, ?, 1, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
                ON CONFLICT(repo, source) DO UPDATE SET
                    fail_count = fail_count + 1,
                    last_failure = BEIJING_TIMESTAMP(),
                    updated_at = BEIJING_TIMESTAMP()
                """,
                (repo, source),
            )
        self.connection.commit()

    def _record_source_validation(
        self,
        repo: str,
        source: str,
        is_valid: bool,
        seconds: float = 0,
        country: str = "",
        failure_category: str = "",
    ) -> None:
        if not repo or not source:
            return
        if is_valid:
            asia_increment = 1 if is_asia_country(country) else 0
            self.connection.execute(
                """
                INSERT INTO "采集来源画像" (
                    repo, source, valid_count, asia_valid_count, valid_seconds_total, last_valid, updated_at
                )
                VALUES (?, ?, 1, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
                ON CONFLICT(repo, source) DO UPDATE SET
                    valid_count = valid_count + 1,
                    asia_valid_count = asia_valid_count + excluded.asia_valid_count,
                    valid_seconds_total = valid_seconds_total + excluded.valid_seconds_total,
                    consecutive_invalid_count = 0,
                    cooldown_until = NULL,
                    last_valid = BEIJING_TIMESTAMP(),
                    updated_at = BEIJING_TIMESTAMP()
                """,
                (repo, source, asia_increment, max(float(seconds or 0), 0.0)),
            )
            return
        failure_category = str(failure_category or "other")[:80]
        current = self.connection.execute(
            """
            SELECT consecutive_invalid_count, valid_count
            FROM "采集来源画像" WHERE repo = ? AND source = ?
            """,
            (repo, source),
        ).fetchone()
        next_consecutive = int(current[0] or 0) + 1 if current else 1
        valid_count = int(current[1] or 0) if current else 0
        cooldown_until = ""
        if next_consecutive >= 20 and valid_count == 0:
            cooldown_until = (beijing_now() + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        elif next_consecutive >= 50:
            cooldown_until = (beijing_now() + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        self.connection.execute(
            """
            INSERT INTO "采集来源画像" (
                repo, source, invalid_count, consecutive_invalid_count,
                cooldown_until, last_failure_category, last_invalid, updated_at
            )
            VALUES (?, ?, 1, ?, NULLIF(?, ''), ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            ON CONFLICT(repo, source) DO UPDATE SET
                invalid_count = invalid_count + 1,
                consecutive_invalid_count = excluded.consecutive_invalid_count,
                cooldown_until = COALESCE(excluded.cooldown_until, cooldown_until),
                last_failure_category = excluded.last_failure_category,
                last_invalid = BEIJING_TIMESTAMP(),
                updated_at = BEIJING_TIMESTAMP()
            """,
            (repo, source, next_consecutive, cooldown_until, failure_category),
        )

    def _increment_daily_ops_stat(
        self,
        category: str,
        name: str,
        count_delta: int = 1,
        total_value_delta: int = 0,
        max_value: int = 0,
        stat_date: str = "",
    ) -> None:
        stat_date = (stat_date or beijing_timestamp()[:10])[:10]
        self.connection.execute(
            """
            INSERT INTO daily_ops_stats (
                stat_date, category, name, count, total_value, max_value, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP())
            ON CONFLICT(stat_date, category, name) DO UPDATE SET
                count = count + excluded.count,
                total_value = total_value + excluded.total_value,
                max_value = MAX(max_value, excluded.max_value),
                updated_at = BEIJING_TIMESTAMP()
            """,
            (
                stat_date,
                str(category or "")[:80],
                str(name or "")[:120],
                int(count_delta or 0),
                int(total_value_delta or 0),
                int(max_value or 0),
            ),
        )

    def record_daily_ops_stat(
        self,
        category: str,
        name: str,
        count_delta: int = 1,
        total_value_delta: int = 0,
        max_value: int = 0,
        stat_date: str = "",
    ) -> None:
        self._increment_daily_ops_stat(category, name, count_delta, total_value_delta, max_value, stat_date)
        self.connection.commit()

    def source_profiles(self, repo: str, limit: int = 200) -> Dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT source, node_count, success_count, fail_count,
                   valid_count, invalid_count, asia_valid_count, cooldown_until
            FROM "采集来源画像"
            WHERE repo = ?
            ORDER BY (
                valid_count * 200 + asia_valid_count * 60 + success_count * 10
                + node_count / 10 - invalid_count * 5 - fail_count * 25
            ) DESC, node_count DESC, success_count DESC, source
            LIMIT ?
            """,
            (repo, limit),
        )
        now = beijing_timestamp()
        profiles = {}
        for source, node_count, success_count, fail_count, valid_count, invalid_count, asia_valid_count, cooldown_until in rows:
            score = source_profile_score(node_count, success_count, fail_count, valid_count, invalid_count, asia_valid_count)
            if cooldown_until and str(cooldown_until) > now:
                score = max(0, score // 10)
            profiles[source] = score
        return profiles

    def top_source_profiles(self, limit: int = 20) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT repo, source, node_count, success_count, fail_count, last_nodes,
                   last_success, last_failure, valid_count, invalid_count, asia_valid_count,
                   valid_seconds_total, last_valid, last_invalid, consecutive_invalid_count,
                   cooldown_until, last_failure_category
            FROM "采集来源画像"
            ORDER BY (
                CASE
                    WHEN cooldown_until IS NOT NULL AND cooldown_until > BEIJING_TIMESTAMP() THEN -100000
                    ELSE 0
                END
                +
                valid_count * 200 + asia_valid_count * 60 + success_count * 10
                + node_count / 10 - invalid_count * 5 - fail_count * 25
            ) DESC, node_count DESC, success_count DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        profiles = []
        for row in rows:
            score = source_profile_score(row[2], row[3], row[4], row[8], row[9], row[10])
            avg_seconds = round(float(row[11] or 0) / int(row[8] or 1), 3) if int(row[8] or 0) else 0
            attempts = int(row[8] or 0) + int(row[9] or 0)
            valid_rate = round(int(row[8] or 0) * 100 / attempts, 2) if attempts else 0
            cooled = bool(row[15] and str(row[15]) > beijing_timestamp())
            profiles.append(
                {
                    "repo": row[0],
                    "source": row[1],
                    "node_count": row[2],
                    "success_count": row[3],
                    "fail_count": row[4],
                    "last_nodes": row[5],
                    "last_success": row[6],
                    "last_failure": row[7],
                    "valid_count": row[8],
                    "invalid_count": row[9],
                    "asia_valid_count": row[10],
                    "avg_seconds": avg_seconds,
                    "valid_rate": valid_rate,
                    "score": score,
                    "tier": source_profile_tier(score, row[8], row[9]),
                    "last_valid": row[12],
                    "last_invalid": row[13],
                    "consecutive_invalid_count": row[14],
                    "cooldown_until": row[15],
                    "last_failure_category": row[16],
                    "cooled_down": cooled,
                }
            )
        return profiles

    def ensure_admin_user(self, username: str, password_hash: str) -> None:
        row = self.connection.execute('SELECT id FROM "后台用户" LIMIT 1').fetchone()
        if row:
            return
        self.connection.execute(
            'INSERT INTO "后台用户" (username, password_hash, created_at, updated_at) VALUES (?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())',
            (username, password_hash),
        )
        self.connection.commit()

    def admin_user_by_username(self, username: str) -> Optional[Dict[str, object]]:
        row = self.connection.execute(
            'SELECT id, username, password_hash FROM "后台用户" WHERE username = ?',
            (username,),
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2]}

    def admin_user_by_session(self, token_hash: str) -> Optional[Dict[str, object]]:
        row = self.connection.execute(
            """
            SELECT u.id, u.username
            FROM "后台会话" s
            JOIN "后台用户" u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > BEIJING_TIMESTAMP()
            """,
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        self.connection.execute(
            'UPDATE "后台会话" SET last_seen_at = BEIJING_TIMESTAMP() WHERE token_hash = ?',
            (token_hash,),
        )
        self.connection.commit()
        return {"id": row[0], "username": row[1]}

    def create_admin_session(self, token_hash: str, user_id: int, expires_at: str, ip: str, user_agent: str) -> None:
        self.connection.execute(
            """
            INSERT INTO "后台会话" (token_hash, user_id, expires_at, ip, user_agent, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            """,
            (token_hash, user_id, expires_at, ip, user_agent[:300]),
        )
        self.connection.execute('UPDATE "后台用户" SET last_login_at = BEIJING_TIMESTAMP() WHERE id = ?', (user_id,))
        self.connection.commit()

    def delete_admin_session(self, token_hash: str) -> None:
        self.connection.execute('DELETE FROM "后台会话" WHERE token_hash = ?', (token_hash,))
        self.connection.commit()

    def prune_admin_sessions(self) -> int:
        cursor = self.connection.execute('DELETE FROM "后台会话" WHERE expires_at <= BEIJING_TIMESTAMP()')
        self.connection.commit()
        return cursor.rowcount

    def update_admin_credentials(self, user_id: int, username: str, password_hash: Optional[str] = None) -> Dict[str, object]:
        if password_hash:
            self.connection.execute(
                """
                UPDATE "后台用户"
                SET username = ?, password_hash = ?, updated_at = BEIJING_TIMESTAMP()
                WHERE id = ?
                """,
                (username, password_hash, user_id),
            )
        else:
            self.connection.execute(
                'UPDATE "后台用户" SET username = ?, updated_at = BEIJING_TIMESTAMP() WHERE id = ?',
                (username, user_id),
            )
        self.connection.commit()
        return {"id": user_id, "username": username}

    def valid_node_count(self, protocol: str = "", country: str = "") -> int:
        clauses = []
        params = []
        if protocol:
            clauses.append("protocol = ?")
            params.append(protocol.lower())
        if country:
            clauses.append("country LIKE ?")
            params.append("%" + country.upper() + "%")
        sql = 'SELECT COUNT(*) FROM "有效节点" WHERE manual_disabled = 0'
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        return self.connection.execute(sql, params).fetchone()[0]

    def valid_node_protocols(self) -> List[str]:
        return [
            row[0] for row in self.connection.execute(
                'SELECT protocol FROM "有效节点" WHERE manual_disabled = 0 GROUP BY protocol ORDER BY protocol'
            )
        ]

    def valid_node_countries(self) -> List[str]:
        countries = set()
        for row in self.connection.execute('SELECT country FROM "有效节点" WHERE manual_disabled = 0 AND country != ""'):
            for country in row[0].split(","):
                country = country.strip().upper()
                if country:
                    countries.add(country)
        return sorted(countries)

    def _valid_node_row(self, row) -> Dict[str, object]:
        meta = uri_metadata(str(row[0]))
        item = {
            "uri": row[0],
            "protocol": row[1],
            "proxy_ips": row[2],
            "seconds": row[3],
            "last_validated": row[4],
            "validation_count": row[5],
            "country": row[6],
            "node_fingerprint": row[7] if len(row) > 7 else node_fingerprint(str(row[0])),
            "source_type": row[8] if len(row) > 8 else "validator",
            "manual_added": bool(row[9]) if len(row) > 9 else False,
            "manual_disabled": bool(row[10]) if len(row) > 10 else False,
            "manual_note": row[11] if len(row) > 11 else "",
            "disabled_at": row[12] if len(row) > 12 else "",
            "disabled_reason": row[13] if len(row) > 13 else "",
            "cf_candidate": bool(row[14]) if len(row) > 14 else is_cf_candidate_uri(str(row[0])),
            "quality_score": node_quality_score(row[3], row[5], row[6]),
            "asia": is_asia_country(row[6]),
            "server": str(meta.get("server") or ""),
            "port": str(meta.get("port") or ""),
            "network": str(meta.get("network") or ""),
            "tls": bool(meta.get("tls")),
        }
        item["publish_region"] = publish_region(item)
        item["publishable"] = is_publishable_region(item)
        pub = self.connection.execute(
            "SELECT publish_enabled, manual_status FROM publish_subscription_pool WHERE uri = ?",
            (str(row[0]),),
        ).fetchone()
        item["published"] = bool(pub and int(pub[0] or 0) == 1 and str(pub[1]) == "publishable")
        return item

    def valid_nodes(
        self,
        limit: int = 50,
        offset: int = 0,
        protocol: str = "",
        country: str = "",
        quality_order: bool = False,
    ) -> List[Dict[str, object]]:
        clauses = []
        params = []
        if protocol:
            clauses.append("protocol = ?")
            params.append(protocol.lower())
        if country:
            clauses.append("country LIKE ?")
            params.append("%" + country.upper() + "%")
        sql = """
            SELECT uri, protocol, proxy_ips, seconds, last_validated, validation_count, country,
                   node_fingerprint, source_type, manual_added, manual_disabled, manual_note,
                   disabled_at, disabled_reason, cf_candidate
            FROM "有效节点"
            WHERE manual_disabled = 0
        """
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        if quality_order:
            sql += """
                ORDER BY seconds ASC, validation_count DESC, last_validated DESC, rowid DESC
                LIMIT ? OFFSET ?
            """
        else:
            sql += """
                ORDER BY last_validated DESC, rowid DESC
                LIMIT ? OFFSET ?
            """
        params.extend([limit, offset])
        return [self._valid_node_row(row) for row in self.connection.execute(sql, params)]

    def all_valid_nodes(self, limit: Optional[int] = None, quality_order: bool = False) -> List[Dict[str, object]]:
        order = "ORDER BY seconds ASC, validation_count DESC, last_validated DESC, rowid DESC" if quality_order else "ORDER BY last_validated DESC, rowid DESC"
        sql = """
            SELECT uri, protocol, proxy_ips, seconds, last_validated, validation_count, country,
                   node_fingerprint, source_type, manual_added, manual_disabled, manual_note,
                   disabled_at, disabled_reason, cf_candidate
            FROM "有效节点"
            WHERE manual_disabled = 0
        """ + order
        params = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.connection.execute(
            sql,
            params,
        )
        return [self._valid_node_row(row) for row in rows]

    def export_valid_nodes(self, limit: int = 100, prefer_asia: bool = True) -> List[Dict[str, object]]:
        limit = max(1, min(int(limit), 10000))
        rows = self.all_valid_nodes(quality_order=True)
        if prefer_asia:
            return final_subscription_nodes(rows, limit)
        return rows[:limit]

    def refresh_premium_subscription_pool(
        self,
        target: int = 20,
        latency_threshold: float = 1.0,
        prefer_asia: bool = True,
    ) -> Dict[str, object]:
        target = normalize_subscription_limit(target)
        latency_threshold = max(0.1, float(latency_threshold or 1.0))
        rows = self.all_valid_nodes(quality_order=True)
        if prefer_asia:
            rows = final_subscription_nodes(rows, MAX_SUBSCRIPTION_TARGET)
        else:
            rows = sorted(rows, key=subscription_sort_key)
        selected: List[Dict[str, object]] = []
        selected_uris = set()
        seen_ips = set()
        country_counts: Dict[str, int] = {}
        protocol_counts: Dict[str, int] = {}

        def country_key(row: Dict[str, object]) -> str:
            return str(row.get("country") or "").split(",", 1)[0].strip().upper() or "UNKNOWN"

        def can_add(row: Dict[str, object], strict: bool) -> bool:
            uri = str(row.get("uri") or "")
            if not uri or uri in selected_uris:
                return False
            if strict and float(row.get("seconds") or 9999) > latency_threshold:
                return False
            proxy_ips = str(row.get("proxy_ips") or "").strip()
            if proxy_ips:
                first_ip = proxy_ips.split(",", 1)[0].strip()
                if first_ip and first_ip in seen_ips:
                    return False
            country = country_key(row)
            protocol = str(row.get("protocol") or "")
            if strict and country_counts.get(country, 0) >= 8:
                return False
            if strict and protocol_counts.get(protocol, 0) >= 8:
                return False
            return True

        def add(row: Dict[str, object], reason: str) -> None:
            selected.append(row)
            selected_uris.add(str(row["uri"]))
            proxy_ips = str(row.get("proxy_ips") or "").strip()
            if proxy_ips:
                first_ip = proxy_ips.split(",", 1)[0].strip()
                if first_ip:
                    seen_ips.add(first_ip)
            country = country_key(row)
            protocol = str(row.get("protocol") or "")
            country_counts[country] = country_counts.get(country, 0) + 1
            protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1
            row["premium_reason"] = reason
            row["premium_score"] = self._publish_score(row)

        for bucket, reason, strict in (
            (rows, "quality_low_latency", True),
            (rows, "quality_relaxed", False),
        ):
            for row in bucket:
                if len(selected) >= target:
                    break
                if can_add(row, strict):
                    add(row, reason)
            if len(selected) >= target:
                break

        if prefer_asia and len(selected) < MIN_SUBSCRIPTION_TARGET:
            for row in self._existing_publishable_premium_nodes():
                if len(selected) >= MIN_SUBSCRIPTION_TARGET:
                    break
                if str(row.get("uri") or "") not in selected_uris:
                    add(row, "retained_publishable_pool")

        self.connection.execute("DELETE FROM premium_subscription_pool")
        self.connection.executemany(
            """
            INSERT INTO premium_subscription_pool (uri, score, reason, selected_at, updated_at)
            VALUES (?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            """,
            [
                (
                    str(row["uri"]),
                    float(row.get("premium_score") or row.get("quality_score") or 0),
                    str(row.get("premium_reason") or ""),
                )
                for row in selected
            ],
        )
        self.connection.commit()
        return {
            "target": target,
            "selected": len(selected),
            "latency_threshold": latency_threshold,
            "valid_nodes": len(rows),
            "nodes": selected,
        }

    def _publish_score(self, row: Dict[str, object]) -> float:
        return subscription_quality_score(row)

    def _existing_publishable_premium_nodes(self) -> List[Dict[str, object]]:
        uri_rows = self.connection.execute(
            "SELECT uri FROM premium_subscription_pool ORDER BY score DESC, updated_at DESC"
        ).fetchall()
        premium_order = {str(row[0]): index for index, row in enumerate(uri_rows)}
        if not premium_order:
            return []
        rows = [
            row for row in self.all_valid_nodes(quality_order=True)
            if str(row.get("uri") or "") in premium_order and is_publishable_region(row)
        ]
        return sorted(rows, key=lambda row: (premium_order.get(str(row.get("uri") or ""), 999999), subscription_sort_key(row)))

    def premium_subscription_pool_fresh(self, limit: int = 20, max_age_minutes: int = 10) -> bool:
        limit = normalize_subscription_limit(limit)
        max_age_minutes = max(1, min(int(max_age_minutes or 10), 1440))
        row = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM premium_subscription_pool p
            JOIN "有效节点" v ON v.uri = p.uri
            WHERE p.updated_at >= datetime(BEIJING_TIMESTAMP(), ?)
            """,
            (f"-{max_age_minutes} minutes",),
        ).fetchone()
        return bool(row and int(row[0] or 0) >= limit)

    def premium_subscription_nodes(
        self,
        limit: int = 20,
        prefer_asia: bool = True,
        latency_threshold: float = 1.0,
    ) -> List[Dict[str, object]]:
        limit = normalize_subscription_limit(limit)
        use_cache = bool(prefer_asia) and float(latency_threshold or 1.0) == 1.0
        if not use_cache or not self.premium_subscription_pool_fresh(limit, 10):
            self.refresh_premium_subscription_pool(limit, latency_threshold, prefer_asia)
        rows = self.connection.execute(
            """
            SELECT v.uri, v.protocol, v.proxy_ips, v.seconds, v.last_validated, v.validation_count,
                   v.country, p.score, p.reason
            FROM premium_subscription_pool p
            JOIN "有效节点" v ON v.uri = p.uri
            ORDER BY p.score DESC, v.seconds ASC, v.validation_count DESC, p.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            item = self._valid_node_row(row[:7])
            item["premium_score"] = row[7]
            item["premium_reason"] = row[8]
            result.append(item)
        if prefer_asia:
            result = final_subscription_nodes(result, limit)
            if len(result) < limit:
                refreshed = self.refresh_premium_subscription_pool(limit, latency_threshold, prefer_asia)
                result = final_subscription_nodes(refreshed.get("nodes", []), limit)
        return result

    def export_subscription_nodes(self, limit: int = DEFAULT_SUBSCRIPTION_TARGET, prefer_asia: bool = True) -> List[Dict[str, object]]:
        return self.premium_subscription_nodes(normalize_subscription_limit(limit), prefer_asia, 1.0)

    def publish_pool_count(self) -> int:
        return int(self.connection.execute(
            "SELECT COUNT(*) FROM publish_subscription_pool WHERE publish_enabled = 1 AND manual_status = 'publishable'"
        ).fetchone()[0])

    def publish_pool_candidates(self, limit: int = 80) -> Dict[str, object]:
        limit = max(1, min(int(limit or 80), 200))
        rows = self.connection.execute(
            """
            SELECT v.uri, v.protocol, v.proxy_ips, v.seconds, v.last_validated, v.validation_count,
                   v.country, v.node_fingerprint, v.source_type, v.manual_added, v.manual_disabled,
                   v.manual_note, v.disabled_at, v.disabled_reason, v.cf_candidate,
                   p.score, p.reason,
                   COALESCE(pub.manual_status, '') AS manual_status,
                   COALESCE(pub.publish_enabled, 0) AS publish_enabled,
                   COALESCE(pub.manual_note, '') AS manual_note
            FROM premium_subscription_pool p
            JOIN "有效节点" v ON v.uri = p.uri
            LEFT JOIN publish_subscription_pool pub ON pub.uri = v.uri
            WHERE v.manual_disabled = 0
            ORDER BY p.score DESC, v.seconds ASC, v.validation_count DESC, p.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        candidates = []
        for row in rows:
            item = self._valid_node_row(row[:15])
            item["premium_score"] = row[15]
            item["premium_reason"] = row[16]
            item["manual_status"] = row[17] or ""
            item["publish_enabled"] = bool(row[18])
            item["manual_note"] = row[19] or item.get("manual_note") or ""
            item.update(uri_metadata(str(item["uri"])))
            candidates.append(self._publish_display_row(item))
        published = self.publish_pool_nodes(200)
        return {
            "candidates": candidates,
            "candidate_count": len(candidates),
            "publish_count": self.publish_pool_count(),
            "published": [self._publish_display_row({**row, **uri_metadata(str(row.get("uri") or "")), "publish_enabled": True, "manual_status": "publishable"}) for row in published],
            "pool": published,
        }

    def _publish_display_row(self, row: Dict[str, object]) -> Dict[str, object]:
        return {
            "uri": str(row.get("uri") or ""),
            "protocol": str(row.get("protocol") or ""),
            "country": str(row.get("country") or ""),
            "server": str(row.get("server") or ""),
            "port": str(row.get("port") or ""),
            "network": str(row.get("network") or ""),
            "tls": bool(row.get("tls")),
            "seconds": float(row.get("seconds") or 0),
            "last_validated": str(row.get("last_validated") or ""),
            "validation_count": int(row.get("validation_count") or 0),
            "premium_score": float(row.get("premium_score") or 0),
            "premium_reason": str(row.get("premium_reason") or ""),
            "manual_status": str(row.get("manual_status") or ""),
            "publish_enabled": bool(row.get("publish_enabled")),
            "manual_note": str(row.get("manual_note") or ""),
            "source_type": str(row.get("source_type") or ""),
            "manual_added": bool(row.get("manual_added")),
            "manual_disabled": bool(row.get("manual_disabled")),
            "cf_candidate": bool(row.get("cf_candidate")),
            "publish_compatible": bool(row.get("publish_compatible")),
            "publish_block_reason": str(row.get("publish_block_reason") or ""),
        }

    def mark_publish_node(self, uri: str, publishable: bool = True, note: str = "") -> Dict[str, object]:
        uri = str(uri or "").strip()
        if not uri:
            raise ValueError("missing uri")
        valid_row = self.connection.execute(
            'SELECT manual_disabled FROM "有效节点" WHERE uri = ?',
            (uri,),
        ).fetchone()
        if not valid_row:
            raise ValueError("有效节点不存在")
        if int(valid_row[0] or 0):
            raise ValueError("节点已禁用，不能发布")
        if self.is_node_blocked(uri):
            raise ValueError("节点已被手动禁用，不能发布")
        meta = uri_metadata(uri)
        status = "publishable" if publishable else "rejected"
        enabled = 1 if publishable else 0
        if publishable and not meta.get("publish_compatible"):
            raise ValueError(str(meta.get("publish_block_reason") or "节点不适合发布"))
        self.connection.execute(
            """
            INSERT INTO publish_subscription_pool (
                uri, name, protocol, server, port, source_pool, manual_status,
                publish_enabled, manual_note, last_checked_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'premium_subscription_pool', ?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            ON CONFLICT(uri) DO UPDATE SET
                protocol = excluded.protocol,
                server = excluded.server,
                port = excluded.port,
                manual_status = excluded.manual_status,
                publish_enabled = excluded.publish_enabled,
                manual_note = excluded.manual_note,
                last_checked_at = BEIJING_TIMESTAMP(),
                updated_at = BEIJING_TIMESTAMP()
            """,
            (
                uri,
                "",
                str(meta.get("protocol") or protocol_of(uri)),
                str(meta.get("server") or ""),
                str(meta.get("port") or ""),
                status,
                enabled,
                str(note or "")[:500],
            ),
        )
        self.connection.execute("DELETE FROM subscription_conversion_cache")
        self.connection.commit()
        return {"uri": uri, "manual_status": status, "publish_enabled": bool(enabled), **meta}

    def remove_publish_node(self, uri: str) -> bool:
        cursor = self.connection.execute("DELETE FROM publish_subscription_pool WHERE uri = ?", (str(uri or ""),))
        self.connection.execute("DELETE FROM subscription_conversion_cache")
        self.connection.commit()
        return bool(cursor.rowcount)

    def clear_publish_pool(self) -> int:
        cursor = self.connection.execute("DELETE FROM publish_subscription_pool")
        self.connection.execute("DELETE FROM subscription_conversion_cache")
        self.connection.commit()
        return int(cursor.rowcount or 0)

    def publish_pool_nodes(self, limit: int = DEFAULT_SUBSCRIPTION_TARGET) -> List[Dict[str, object]]:
        limit = max(1, min(int(limit or DEFAULT_SUBSCRIPTION_TARGET), MAX_SUBSCRIPTION_TARGET))
        rows = self.connection.execute(
            """
            SELECT v.uri, v.protocol, v.proxy_ips, v.seconds, v.last_validated, v.validation_count,
                   v.country, v.node_fingerprint, v.source_type, v.manual_added, v.manual_disabled,
                   v.manual_note, v.disabled_at, v.disabled_reason, v.cf_candidate,
                   pub.manual_status, pub.manual_note, pub.updated_at
            FROM publish_subscription_pool pub
            JOIN "有效节点" v ON v.uri = pub.uri
            WHERE pub.publish_enabled = 1 AND pub.manual_status = 'publishable' AND v.manual_disabled = 0
            ORDER BY pub.updated_at DESC, v.seconds ASC, v.validation_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            item = self._valid_node_row(row[:15])
            meta = uri_metadata(str(item["uri"]))
            if not meta.get("publish_compatible"):
                continue
            item["source_pool"] = "publish_pool"
            item["manual_status"] = row[15]
            item["manual_note"] = row[16]
            item["publish_updated_at"] = row[17]
            result.append(item)
        return final_subscription_nodes(result, limit)

    def export_publish_subscription_nodes(self, limit: int = DEFAULT_SUBSCRIPTION_TARGET) -> List[Dict[str, object]]:
        return self.publish_pool_nodes(normalize_subscription_limit(limit))

    def iter_valid_nodes(self, limit: int = 50, prefer_asia: bool = True) -> Iterator[str]:
        for row in self.export_valid_nodes(limit, prefer_asia):
            yield str(row["uri"])

    def create_subscription_link(
        self,
        token: str,
        name: str,
        mode: str,
        max_uses: Optional[int] = None,
        expires_at: Optional[str] = None,
        rename_template: str = "",
        remark: str = "",
        export_limit: int = DEFAULT_SUBSCRIPTION_TARGET,
        claim_code_version: str = "",
    ) -> Dict[str, object]:
        if mode not in ("usage", "time", "either"):
            raise ValueError("unknown subscription mode: " + mode)
        export_limit = normalize_subscription_limit(export_limit)
        claim_code_version = str(claim_code_version or self.claim_code_config()["version"]).strip()
        self.connection.execute(
            """
            INSERT INTO "订阅链接" (
                token, name, mode, claim_code_version, max_uses, export_limit, expires_at,
                rename_template, remark, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            """,
            (token, name, mode, claim_code_version, max_uses, export_limit, expires_at, rename_template, remark),
        )
        self.connection.commit()
        return self.subscription_link(token) or {}

    def subscription_link(self, token: str) -> Optional[Dict[str, object]]:
        row = self.connection.execute(
            """
            SELECT token, name, mode, enabled, claim_code_version, max_uses, export_limit, used_count, expires_at,
                   rename_template, remark, created_at, updated_at, last_used_at, last_used_ip
            FROM "订阅链接"
            WHERE token = ?
            """,
            (token,),
        ).fetchone()
        return self._subscription_row(row) if row else None

    def subscription_links(self, limit: int = 100) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT token, name, mode, enabled, claim_code_version, max_uses, export_limit, used_count, expires_at,
                   rename_template, remark, created_at, updated_at, last_used_at, last_used_ip
            FROM "订阅链接"
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._subscription_row(row) for row in rows]

    def touch_subscription_link(self, token: str, ip: str) -> None:
        self.connection.execute(
            """
            UPDATE "订阅链接"
            SET used_count = used_count + 1,
                last_used_at = BEIJING_TIMESTAMP(),
                last_used_ip = ?,
                updated_at = BEIJING_TIMESTAMP()
            WHERE token = ?
            """,
            (ip, token),
        )
        self.connection.commit()

    def set_subscription_enabled(self, token: str, enabled: bool) -> Optional[Dict[str, object]]:
        self.connection.execute(
            'UPDATE "订阅链接" SET enabled = ?, updated_at = BEIJING_TIMESTAMP() WHERE token = ?',
            (1 if enabled else 0, token),
        )
        self.connection.commit()
        return self.subscription_link(token)

    def delete_subscription_link(self, token: str) -> bool:
        cursor = self.connection.execute('DELETE FROM "订阅链接" WHERE token = ?', (token,))
        self.connection.commit()
        return cursor.rowcount > 0

    def _subscription_row(self, row) -> Dict[str, object]:
        return {
            "token": row[0],
            "name": row[1],
            "mode": row[2],
            "enabled": bool(row[3]),
            "claim_code_version": row[4],
            "max_uses": row[5],
            "export_limit": row[6],
            "used_count": row[7],
            "expires_at": row[8],
            "rename_template": row[9],
            "remark": row[10],
            "created_at": row[11],
            "updated_at": row[12],
            "last_used_at": row[13],
            "last_used_ip": row[14],
        }

    def bot_config_defaults(self) -> Dict[str, object]:
        return {
            "bot_token": "",
            "bot_username": "",
            "auto_run": False,
            "keywords": "节点\n订阅\nVMTOK",
            "group_prompt_message": "请点击下方按钮私聊 BOT 领取最新免费节点。进入私聊后无需再次发送群关键词，按提示发送视频内口令即可。",
            "private_instruction_message": (
                "{youtube_guide_message}\n\n"
                "当前口令版本：{version}\n"
                "口令有效期：{expires_at}\n\n"
                "请直接发送视频内口令完成轻量验证。"
            ),
            "subscription_card_message": (
                "领取成功，下面是你的订阅卡片：\n\n"
                "V2RayNG / Base64：{subscription_url}\n"
                "Clash Verge：{subscription_url}\n"
                "Sing-box：{subscription_url}\n"
                "Surge：{subscription_url}\n"
                "Shadowrocket 小火箭：{subscription_url}\n\n"
                "有效期：{expires_at}\n"
                "最多访问：{max_uses} 次"
            ),
            "youtube_url": "",
            "youtube_channel_id": "",
            "youtube_channel_url": "",
            "latest_free_node_video_url": "",
            "youtube_guide_message": (
                "请先订阅我们的 YouTube 频道，并观看最新免费节点领取视频。\n\n"
                "YouTube 频道：{youtube_channel_url}\n"
                "最新领取视频：{latest_free_node_video_url}\n\n"
                "视频内会公布当前领取口令。回到私聊发送口令，即可完成轻量验证。"
            ),
            "public_base_url": "https://node.huage.us",
            "verify_link_minutes": 30,
            "subscription_max_uses": 10,
            "subscription_expire_hours": 24,
            "subscription_export_limit": DEFAULT_SUBSCRIPTION_TARGET,
            "welcome_message": (
                "欢迎使用 VMTOK 验证系统\n\n"
                "请完成 YouTube 频道订阅验证：\n\n"
                "1. 订阅我们的 YouTube 频道\n\n"
                "2. 点击下面按钮完成验证"
            ),
            "unverified_message": "节点维护不容易，请先完成 YouTube 频道订阅验证。",
            "success_message": "验证成功，感谢你的支持。",
        }

    def bot_config(self, mask_secrets: bool = False) -> Dict[str, object]:
        config = self.bot_config_defaults()
        rows = dict(self.connection.execute('SELECT key, value FROM "Bot配置"'))
        config.update({key: value for key, value in rows.items() if key in config})
        config["auto_run"] = str(config["auto_run"]).lower() in ("1", "true", "yes", "on")
        try:
            config["verify_link_minutes"] = int(config["verify_link_minutes"])
        except (TypeError, ValueError):
            config["verify_link_minutes"] = 30
        for key, default, minimum, maximum in (
            ("subscription_max_uses", 10, 1, 1000000),
            ("subscription_expire_hours", 24, 1, 8760),
            ("subscription_export_limit", DEFAULT_SUBSCRIPTION_TARGET, 1, MAX_SUBSCRIPTION_TARGET),
        ):
            try:
                config[key] = max(minimum, min(int(config[key]), maximum))
            except (TypeError, ValueError):
                config[key] = default
        token = str(config["bot_token"])
        config["bot_username"] = normalize_bot_username_value(config.get("bot_username"))
        private_start_url = bot_private_start_url_value(config["bot_username"], "claim")
        config["bot_private_start_url"] = private_start_url
        config["claim_entry_ok"] = bool(private_start_url)
        config["claim_entry_reason"] = (
            "群按钮将打开 Telegram 私聊领取"
            if private_start_url
            else "Bot 用户名未配置，群按钮无法生成 Telegram 私聊入口"
        )
        config["token_configured"] = bool(token)
        if mask_secrets and token:
            config["bot_token"] = token[:6] + "..." + token[-4:]
        return config

    def update_bot_config(self, values: Dict[str, object]) -> Dict[str, object]:
        defaults = self.bot_config_defaults()
        cleaned = {}
        for key in defaults:
            if key not in values:
                continue
            value = values[key]
            if key == "verify_link_minutes":
                value = max(1, min(int(value), 1440))
            elif key == "subscription_max_uses":
                value = max(1, min(int(value), 1000000))
            elif key == "subscription_expire_hours":
                value = max(1, min(int(value), 8760))
            elif key == "subscription_export_limit":
                value = normalize_subscription_limit(value)
            elif key == "auto_run":
                value = "1" if value is True or str(value).lower() in ("1", "true", "yes", "on") else "0"
            elif key == "bot_username":
                value = normalize_bot_username_value(value)
            else:
                value = str(value).strip()
            cleaned[key] = value
        if cleaned:
            self.connection.executemany(
                """
                INSERT INTO "Bot配置" (key, value, updated_at)
                VALUES (?, ?, BEIJING_TIMESTAMP())
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = BEIJING_TIMESTAMP()
                """,
                [(key, str(value)) for key, value in cleaned.items()],
            )
            self.connection.commit()
        return self.bot_config(mask_secrets=True)

    def create_bot_verification(
        self,
        token: str,
        telegram_user_id: str,
        telegram_chat_id: str,
        username: str,
        expires_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO "Bot验证任务" (
                token, telegram_user_id, telegram_chat_id, username, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, BEIJING_TIMESTAMP())
            """,
            (token, telegram_user_id, telegram_chat_id, username, expires_at),
        )
        self.connection.commit()

    def bot_verification(self, token: str) -> Optional[Dict[str, object]]:
        row = self.connection.execute(
            """
            SELECT token, telegram_user_id, telegram_chat_id, username, status, created_at, expires_at, completed_at
            FROM "Bot验证任务" WHERE token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        return {
            "token": row[0],
            "telegram_user_id": row[1],
            "telegram_chat_id": row[2],
            "username": row[3],
            "status": row[4],
            "created_at": row[5],
            "expires_at": row[6],
            "completed_at": row[7],
        }

    def record_bot_message(self, user_id: str, chat_id: str, direction: str, message: str) -> None:
        self.connection.execute(
            """
            INSERT INTO "Bot消息日志" (telegram_user_id, telegram_chat_id, direction, message, created_at)
            VALUES (?, ?, ?, ?, BEIJING_TIMESTAMP())
            """,
            (user_id, chat_id, direction, message[:2000]),
        )
        self.connection.commit()

    def bot_message_logs(self, limit: int = 50) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT telegram_user_id, telegram_chat_id, direction, message, created_at
            FROM "Bot消息日志" ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "telegram_user_id": row[0],
                "telegram_chat_id": row[1],
                "direction": row[2],
                "message": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def claim_code_defaults(self) -> Dict[str, object]:
        return {
            "enabled": True,
            "code": "VMTOK",
            "version": "v1",
            "expires_at": "",
            "daily_limit": 1,
            "success_message": "领取成功，请按页面提示继续操作。",
            "wrong_code_message": "口令错误，请检查后重新输入。",
            "expired_message": "口令已过期，请获取最新口令后再试。",
            "limit_exceeded_message": "今日领取次数已用完，请明天再试。",
        }

    def claim_code_config(self) -> Dict[str, object]:
        config = self.claim_code_defaults()
        rows = dict(self.connection.execute('SELECT key, value FROM "领取口令配置"'))
        config.update({key: value for key, value in rows.items() if key in config})
        config["enabled"] = str(config["enabled"]).lower() in ("1", "true", "yes", "on")
        try:
            config["daily_limit"] = max(1, min(int(config["daily_limit"]), 1000000))
        except (TypeError, ValueError):
            config["daily_limit"] = 1
        return config

    def update_claim_code_config(self, values: Dict[str, object]) -> Dict[str, object]:
        defaults = self.claim_code_defaults()
        cleaned = {}
        for key in defaults:
            if key not in values:
                continue
            value = values[key]
            if key == "enabled":
                value = "1" if value is True or str(value).lower() in ("1", "true", "yes", "on") else "0"
            elif key == "daily_limit":
                value = str(max(1, min(int(value), 1000000)))
            else:
                value = str(value).strip()
                if key in ("code", "version") and not value:
                    value = str(defaults[key])
            cleaned[key] = value
        if cleaned:
            self.connection.executemany(
                """
                INSERT INTO "领取口令配置" (key, value, updated_at)
                VALUES (?, ?, BEIJING_TIMESTAMP())
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = BEIJING_TIMESTAMP()
                """,
                [(key, str(value)) for key, value in cleaned.items()],
            )
            self.connection.commit()
        return self.claim_code_config()

    def claim_success_count(self, claim_date: str, client_key: str, version: str) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) FROM "领取记录"
            WHERE claim_date = ? AND client_key = ? AND version = ? AND status = 'success'
            """,
            (claim_date, client_key, version),
        ).fetchone()
        return int(row[0]) if row else 0

    def record_claim_attempt(
        self,
        claim_date: str,
        client_key: str,
        version: str,
        code: str,
        status: str,
        ip: str = "",
        user_agent: str = "",
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO "领取记录" (
                claim_date, client_key, version, code, status, ip, user_agent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP())
            """,
            (claim_date, client_key, version, code[:200], status, ip, user_agent[:500]),
        )
        self.connection.commit()

    def maintenance_defaults(self) -> Dict[str, object]:
        return {
            "enabled": True,
            "schedule_hour": 3,
            "schedule_minute": 30,
            "converter_log_days": 7,
            "converter_log_max_rows": 5000,
            "bot_log_days": 7,
            "bot_log_max_rows": 5000,
            "claim_record_days": 7,
            "subscription_access_days": 7,
            "subscription_access_max_rows": 10000,
            "maintenance_record_days": 30,
            "stale_unvalidated_node_days": 2,
            "invalid_node_days": 30,
            "bot_verification_days": 7,
            "conversion_cache_days": 7,
            "conversion_cache_max_rows": 1000,
            "daily_stats_days": 365,
            "acceptance_report_days": 7,
            "acceptance_failed_report_days": 30,
            "acceptance_report_max_files": 120,
            "vacuum_after_cleanup": False,
        }

    def maintenance_config(self) -> Dict[str, object]:
        config = self.maintenance_defaults()
        rows = dict(self.connection.execute('SELECT key, value FROM "系统维护配置"'))
        config.update({key: value for key, value in rows.items() if key in config})
        bool_keys = {"enabled", "vacuum_after_cleanup"}
        for key in bool_keys:
            config[key] = str(config[key]).lower() in ("1", "true", "yes", "on")
        ranges = {
            "schedule_hour": (0, 23),
            "schedule_minute": (0, 59),
            "converter_log_days": (1, 3650),
            "converter_log_max_rows": (100, 1000000),
            "bot_log_days": (1, 3650),
            "bot_log_max_rows": (100, 1000000),
            "claim_record_days": (1, 3650),
            "subscription_access_days": (1, 3650),
            "subscription_access_max_rows": (100, 1000000),
            "maintenance_record_days": (1, 3650),
            "stale_unvalidated_node_days": (1, 3650),
            "invalid_node_days": (1, 3650),
            "bot_verification_days": (1, 3650),
            "conversion_cache_days": (1, 3650),
            "conversion_cache_max_rows": (10, 1000000),
            "daily_stats_days": (30, 3650),
            "acceptance_report_days": (1, 3650),
            "acceptance_failed_report_days": (1, 3650),
            "acceptance_report_max_files": (10, 1000000),
        }
        for key, (low, high) in ranges.items():
            try:
                config[key] = max(low, min(int(config[key]), high))
            except (TypeError, ValueError):
                config[key] = self.maintenance_defaults()[key]
        return config

    def update_maintenance_config(self, values: Dict[str, object]) -> Dict[str, object]:
        defaults = self.maintenance_defaults()
        cleaned = {}
        for key in defaults:
            if key not in values:
                continue
            if isinstance(defaults[key], bool):
                cleaned[key] = "1" if values[key] is True or str(values[key]).lower() in ("1", "true", "yes", "on") else "0"
            else:
                cleaned[key] = str(int(values[key]))
        if cleaned:
            self.connection.executemany(
                """
                INSERT INTO "系统维护配置" (key, value, updated_at)
                VALUES (?, ?, BEIJING_TIMESTAMP())
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = BEIJING_TIMESTAMP()
                """,
                list(cleaned.items()),
            )
            self.connection.commit()
        return self.maintenance_config()

    def record_subscription_access(
        self,
        access_date: str,
        token: str,
        status: str,
        ip_hash: str,
        user_agent_hash: str,
        node_count: int = 0,
        latency_ms: int = 0,
        message: str = "",
        source: str = "",
        export_count: Optional[int] = None,
    ) -> None:
        node_count = max(0, int(node_count or 0))
        latency_ms = max(0, int(latency_ms or 0))
        if export_count is None:
            export_count = node_count
        export_count = max(0, int(export_count or 0))
        self.connection.execute(
            """
            INSERT INTO "订阅访问日志" (
                access_date, token, status, ip_hash, user_agent_hash,
                node_count, latency_ms, source, export_count, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP())
            """,
            (
                access_date,
                token[:80],
                status[:80],
                ip_hash[:80],
                user_agent_hash[:80],
                node_count,
                latency_ms,
                str(source or "")[:80],
                export_count,
                message[:500],
            ),
        )
        self.connection.execute(
            """
            INSERT INTO "订阅访问汇总" (
                access_date, token, status, count, node_count,
                latency_total_ms, latency_max_ms, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?, BEIJING_TIMESTAMP())
            ON CONFLICT(access_date, token, status) DO UPDATE SET
                count = count + 1,
                node_count = node_count + excluded.node_count,
                latency_total_ms = latency_total_ms + excluded.latency_total_ms,
                latency_max_ms = MAX(latency_max_ms, excluded.latency_max_ms),
                updated_at = BEIJING_TIMESTAMP()
            """,
            (access_date, token[:80], status[:80], node_count, latency_ms, latency_ms),
        )
        self.connection.commit()

    def refresh_daily_ops_stats(self) -> int:
        touched = 0
        sources = []
        claim_table = self._table_with_columns(("claim_date", "client_key", "version", "status"))
        converter_table = self._table_with_columns(("target_id", "input_mode", "output_bytes", "status"))
        bot_table = self._table_with_columns(("telegram_user_id", "telegram_chat_id", "direction", "message"))
        access_summary_table = self._table_with_columns(("access_date", "token", "status", "latency_total_ms"))
        if claim_table:
            sources.append((
                "claim",
                'SELECT claim_date, status, COUNT(*), 0, 0 FROM "' + claim_table + '" GROUP BY claim_date, status',
            ))
        if converter_table:
            sources.append((
                "converter",
                'SELECT substr(created_at, 1, 10), target_id || ":" || status, '
                'COUNT(*), COALESCE(SUM(output_bytes), 0), COALESCE(MAX(output_bytes), 0) '
                'FROM "' + converter_table + '" GROUP BY substr(created_at, 1, 10), target_id, status',
            ))
        if bot_table:
            sources.append((
                "bot",
                'SELECT substr(created_at, 1, 10), direction, COUNT(*), 0, 0 '
                'FROM "' + bot_table + '" GROUP BY substr(created_at, 1, 10), direction',
            ))
        if access_summary_table:
            sources.append((
                "subscription_access",
                'SELECT access_date, status, COALESCE(SUM(count), 0), '
                'COALESCE(SUM(node_count), 0), COALESCE(MAX(latency_max_ms), 0) '
                'FROM "' + access_summary_table + '" GROUP BY access_date, status',
            ))
        for category, query in sources:
            try:
                rows = self.connection.execute(query).fetchall()
            except sqlite3.Error:
                continue
            for stat_date, name, count, total_value, max_value in rows:
                if not stat_date:
                    continue
                self.connection.execute(
                    """
                    INSERT INTO daily_ops_stats (
                        stat_date, category, name, count, total_value, max_value, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP())
                    ON CONFLICT(stat_date, category, name) DO UPDATE SET
                        count = excluded.count,
                        total_value = excluded.total_value,
                        max_value = excluded.max_value,
                        updated_at = BEIJING_TIMESTAMP()
                    """,
                    (
                        str(stat_date)[:10],
                        category,
                        str(name or "")[:120],
                        int(count or 0),
                        int(total_value or 0),
                        int(max_value or 0),
                    ),
                )
                touched += 1
        today = beijing_timestamp()[:10]
        snapshots = {
            "nodes:raw": self._count_table_with_columns(("uri", "repo", "source", "seen_count")),
            "nodes:valid": self._count_table_with_columns(("uri", "country", "last_validated", "validation_count")),
            "nodes:invalid": self._count_table_with_columns(("uri", "reason", "last_validated", "validation_count"), exclude_columns=("country",)),
        }
        for name, count in snapshots.items():
            self.connection.execute(
                """
                INSERT INTO daily_ops_stats (
                    stat_date, category, name, count, total_value, max_value, updated_at
                ) VALUES (?, 'snapshot', ?, ?, 0, 0, BEIJING_TIMESTAMP())
                ON CONFLICT(stat_date, category, name) DO UPDATE SET
                    count = excluded.count,
                    updated_at = BEIJING_TIMESTAMP()
                """,
                (today, name, int(count or 0)),
            )
            touched += 1
        self.connection.commit()
        return touched

    def _table_with_columns(self, required: Sequence[str], exclude_columns: Sequence[str] = ()) -> str:
        required_set = set(required)
        exclude_set = set(exclude_columns)
        rows = self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        for (name,) in rows:
            quoted = str(name).replace('"', '""')
            try:
                columns = {row[1] for row in self.connection.execute('PRAGMA table_info("' + quoted + '")')}
            except sqlite3.Error:
                continue
            if required_set.issubset(columns) and not exclude_set.intersection(columns):
                return str(name)
        return ""

    def _count_table_with_columns(self, required: Sequence[str], exclude_columns: Sequence[str] = ()) -> int:
        table = self._table_with_columns(required, exclude_columns)
        if not table:
            return 0
        row = self.connection.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()
        return int(row[0] or 0) if row else 0

    def daily_ops_stats(self, limit: int = 30) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT stat_date, category, name, count, total_value, max_value, updated_at
            FROM daily_ops_stats
            ORDER BY stat_date DESC, category, name
            LIMIT ?
            """,
            (max(1, min(int(limit or 30), 200)),),
        ).fetchall()
        keys = ("stat_date", "category", "name", "count", "total_value", "max_value", "updated_at")
        return [dict(zip(keys, row)) for row in rows]

    def ops_trend_stats(self, days: int = 7) -> Dict[str, object]:
        days = max(1, min(int(days or 7), 90))
        self.refresh_daily_ops_stats()
        rows = self.connection.execute(
            """
            SELECT stat_date, category, name, count, total_value, max_value, updated_at
            FROM daily_ops_stats
            WHERE stat_date >= date(BEIJING_TIMESTAMP(), ?)
            ORDER BY stat_date ASC, category, name
            """,
            ("-" + str(days - 1) + " days",),
        ).fetchall()
        keys = ("stat_date", "category", "name", "count", "total_value", "max_value", "updated_at")
        return {
            "days": days,
            "rows": [dict(zip(keys, row)) for row in rows],
        }

    def maintenance_overview(self) -> Dict[str, object]:
        tables = [
            "节点库", "有效节点", "无效节点", "订阅链接",
            "订阅转换日志", "Bot消息日志", "领取记录",
            "订阅访问日志", "订阅访问汇总", "系统维护记录",
        ]
        counts = {}
        for table in tables:
            try:
                row = self.connection.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()
                counts[table] = int(row[0]) if row else 0
            except sqlite3.Error:
                counts[table] = 0
        try:
            row = self.connection.execute('SELECT COUNT(*) FROM subscription_conversion_cache').fetchone()
            counts["subscription_conversion_cache"] = int(row[0]) if row else 0
        except sqlite3.Error:
            counts["subscription_conversion_cache"] = 0
        try:
            row = self.connection.execute("SELECT COUNT(*) FROM daily_ops_stats").fetchone()
            counts["daily_ops_stats"] = int(row[0]) if row else 0
        except sqlite3.Error:
            counts["daily_ops_stats"] = 0
        last = self.connection.execute(
            """
            SELECT reason, deleted_rows, details, database_bytes_before, database_bytes_after, created_at
            FROM "系统维护记录"
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        return {
            "config": self.maintenance_config(),
            "database_bytes": self.database_size_bytes(),
            "table_counts": counts,
            "conversion_cache": self.subscription_conversion_cache_stats(),
            "daily_stats": self.daily_ops_stats(30),
            "last_cleanup": {
                "reason": last[0],
                "deleted_rows": last[1],
                "details": last[2],
                "database_bytes_before": last[3],
                "database_bytes_after": last[4],
                "created_at": last[5],
            } if last else None,
        }

    def database_size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            if path.exists():
                total += path.stat().st_size
        return total

    def run_maintenance_cleanup(
        self,
        reason: str = "manual",
        config: Optional[Dict[str, object]] = None,
        extra_details: Optional[Dict[str, int]] = None,
    ) -> Dict[str, object]:
        config = config or self.maintenance_config()
        before = self.database_size_bytes()
        details: Dict[str, int] = {}
        details["daily_ops_stats_refreshed"] = self.refresh_daily_ops_stats()
        details["订阅转换日志_过期"] = self._delete_older_than("订阅转换日志", "created_at", int(config["converter_log_days"]))
        details["订阅转换日志_超量"] = self._trim_by_id("订阅转换日志", int(config["converter_log_max_rows"]))
        details["Bot消息日志_过期"] = self._delete_older_than("Bot消息日志", "created_at", int(config["bot_log_days"]))
        details["Bot消息日志_超量"] = self._trim_by_id("Bot消息日志", int(config["bot_log_max_rows"]))
        details["领取记录_过期"] = self._delete_older_than("领取记录", "created_at", int(config["claim_record_days"]))
        details["订阅访问日志_过期"] = self._delete_older_than("订阅访问日志", "created_at", int(config["subscription_access_days"]))
        details["订阅访问日志_超量"] = self._trim_by_id("订阅访问日志", int(config["subscription_access_max_rows"]))
        details.update(self.cleanup_stale_unvalidated_nodes(int(config["stale_unvalidated_node_days"])))
        details["无效节点_过期"] = self._delete_older_than("无效节点", "last_validated", int(config["invalid_node_days"]))
        details["Bot验证任务_过期"] = self._delete_older_than("Bot验证任务", "created_at", int(config["bot_verification_days"]))
        details["系统维护记录_过期"] = self._delete_older_than("系统维护记录", "created_at", int(config["maintenance_record_days"]))
        details["subscription_conversion_cache_expired"] = self._delete_older_than(
            "subscription_conversion_cache",
            "last_accessed_at",
            int(config["conversion_cache_days"]),
        )
        details["subscription_conversion_cache_overflow"] = self._trim_table_by_column(
            "subscription_conversion_cache",
            "last_accessed_at",
            int(config["conversion_cache_max_rows"]),
        )
        details["daily_ops_stats_expired"] = self._delete_older_than(
            "daily_ops_stats",
            "stat_date",
            int(config["daily_stats_days"]),
        )
        for key, value in (extra_details or {}).items():
            details[str(key)[:120]] = int(value or 0)
        total = sum(value for key, value in details.items() if not key.endswith("_refreshed"))
        if config.get("vacuum_after_cleanup") and total > 0:
            self.connection.commit()
            self.connection.execute("VACUUM")
        after = self.database_size_bytes()
        self.connection.execute(
            """
            INSERT INTO "系统维护记录" (
                reason, deleted_rows, details, database_bytes_before,
                database_bytes_after, created_at
            ) VALUES (?, ?, ?, ?, ?, BEIJING_TIMESTAMP())
            """,
            (reason, total, json.dumps(details, ensure_ascii=False), before, after),
        )
        self.connection.commit()
        return {
            "reason": reason,
            "deleted_rows": total,
            "details": details,
            "database_bytes_before": before,
            "database_bytes_after": after,
        }

    def _delete_older_than(self, table: str, column: str, days: int) -> int:
        cursor = self.connection.execute(
            'DELETE FROM "' + table + '" WHERE "' + column + '" IS NOT NULL AND "' + column + '" < datetime(BEIJING_TIMESTAMP(), ?)',
            ("-" + str(max(1, int(days))) + " days",),
        )
        return int(cursor.rowcount or 0)

    def _trim_by_id(self, table: str, max_rows: int) -> int:
        max_rows = max(1, int(max_rows))
        cursor = self.connection.execute(
            'DELETE FROM "' + table + '" WHERE id NOT IN (SELECT id FROM "' + table + '" ORDER BY id DESC LIMIT ?)',
            (max_rows,),
        )
        return int(cursor.rowcount or 0)

    def _trim_table_by_column(self, table: str, column: str, max_rows: int) -> int:
        max_rows = max(1, int(max_rows))
        cursor = self.connection.execute(
            'DELETE FROM "' + table + '" WHERE rowid NOT IN (SELECT rowid FROM "' + table + '" ORDER BY "' + column + '" DESC LIMIT ?)',
            (max_rows,),
        )
        return int(cursor.rowcount or 0)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "NodeDatabase":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
