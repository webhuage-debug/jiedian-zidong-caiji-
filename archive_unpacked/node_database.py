#!/usr/bin/env python3
"""SQLite storage shared by the crawler and Xray validator."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from app_time import beijing_timestamp


ASIA_COUNTRIES = ("HK", "JP", "SG", "TW", "KR", "TH", "VN", "MY", "PH", "IN", "ID", "MO")
ASIA_KEYWORDS = (
    "香港", "日本", "新加坡", "台湾", "韓國", "韩国",
    "hk", "jp", "sg", "tw", "kr", "hkg", "jpn", "sin", "tpe", "sel",
    "hongkong", "hong kong", "japan", "singapore", "taiwan", "korea",
)


def protocol_of(uri: str) -> str:
    return uri.split("://", 1)[0].lower() if "://" in uri else ""


def asia_priority_sql(column: str = "country") -> str:
    cases = " ".join(
        "WHEN UPPER(" + column + ") LIKE '%" + country + "%' THEN " + str(index)
        for index, country in enumerate(ASIA_COUNTRIES)
    )
    return "CASE " + cases + " ELSE 999 END"


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
                first_validated TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_validated TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                validation_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS "有效节点_协议" ON "有效节点" (protocol);

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
                max_uses INTEGER,
                used_count INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                rename_template TEXT NOT NULL DEFAULT '',
                remark TEXT NOT NULL DEFAULT '',
                claim_version TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT 'manual',
                telegram_user_id TEXT NOT NULL DEFAULT '',
                telegram_username TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                last_used_at TEXT,
                last_used_ip TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS "订阅链接_状态" ON "订阅链接" (enabled, mode, expires_at);

            CREATE TABLE IF NOT EXISTS "领取口令配置" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "Bot领取状态" (
                telegram_user_id TEXT PRIMARY KEY,
                telegram_chat_id TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );

            CREATE TABLE IF NOT EXISTS "Bot领取记录" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id TEXT NOT NULL,
                telegram_username TEXT NOT NULL DEFAULT '',
                claim_version TEXT NOT NULL DEFAULT '',
                subscription_token TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            );
            CREATE INDEX IF NOT EXISTS "Bot领取记录_用户日期" ON "Bot领取记录" (telegram_user_id, created_at);

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
            """
        )
        self._add_missing_columns()
        self._migrate_beijing_timestamps()
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
        if "country" not in valid_columns:
            self.connection.execute('ALTER TABLE "有效节点" ADD COLUMN "country" TEXT NOT NULL DEFAULT ""')
        subscription_columns = {row[1] for row in self.connection.execute('PRAGMA table_info("订阅链接")')}
        subscription_migrations = {
            "claim_version": "TEXT NOT NULL DEFAULT ''",
            "created_by": "TEXT NOT NULL DEFAULT 'manual'",
            "telegram_user_id": "TEXT NOT NULL DEFAULT ''",
            "telegram_username": "TEXT NOT NULL DEFAULT ''",
        }
        for name, declaration in subscription_migrations.items():
            if name not in subscription_columns:
                self.connection.execute('ALTER TABLE "订阅链接" ADD COLUMN "' + name + '" ' + declaration)
        self.connection.execute('DELETE FROM "自动控制配置" WHERE key = "validator_limit"')

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
            "后台用户": ("created_at", "updated_at", "last_login_at"),
            "后台会话": ("created_at", "expires_at", "last_seen_at"),
            "订阅链接": ("created_at", "updated_at", "last_used_at"),
            "Bot配置": ("updated_at",),
            "领取口令配置": ("updated_at",),
            "Bot领取状态": ("updated_at",),
            "Bot领取记录": ("created_at",),
            "Bot验证任务": ("created_at", "expires_at", "completed_at"),
            "Bot消息日志": ("created_at",),
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
        upsert_rows = [row for row in unique_rows.values() if row[0] not in existing_verified]
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
            "inserted": len(unique_rows) - len(existing),
            "duplicates": duplicate_count,
            "total": self.count("节点库"),
            "inserted_uris": [uri for uri in unique_rows if uri not in existing],
        }

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
        if status == "无效":
            self.connection.execute(
                """
                INSERT INTO "系统统计" (key, value) VALUES ('invalid_nodes_total', 1)
                ON CONFLICT(key) DO UPDATE SET value = value + 1
                """
            )
            self.connection.execute('DELETE FROM "有效节点" WHERE uri = ?', (uri,))
            self.connection.execute('DELETE FROM "节点库" WHERE uri = ?', (uri,))
            self.connection.commit()
            return
        self.connection.execute(
            """
            INSERT INTO "有效节点" (uri, protocol, reason, seconds, proxy_ips, country, first_validated, last_validated)
            VALUES (?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            ON CONFLICT(uri) DO UPDATE SET
                reason = excluded.reason,
                seconds = excluded.seconds,
                proxy_ips = excluded.proxy_ips,
                country = excluded.country,
                last_validated = BEIJING_TIMESTAMP(),
                validation_count = "有效节点".validation_count + 1
            """,
            (uri, protocol_of(uri), reason, seconds, proxy_ips or "", country),
        )
        self.connection.execute('DELETE FROM "节点库" WHERE uri = ?', (uri,))
        self.connection.commit()

    def upsert_valid_node(self, uri: str, reason: str, seconds: float, proxy_ips: Optional[str] = None, country: str = "") -> None:
        self.record_validation(uri, "有效", reason, seconds, proxy_ips, country)

    def count(self, table: str) -> int:
        if table not in ("节点库", "有效节点"):
            raise ValueError("unknown table: " + table)
        return self.connection.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]

    def iter_nodes(self, protocols: Sequence[str] = (), revalidate: bool = False) -> Iterator[str]:
        clauses = []
        params = []
        if protocols:
            placeholders = ",".join("?" for _ in protocols)
            clauses.append("protocol IN (" + placeholders + ")")
            params.extend(protocol.lower() for protocol in protocols)
        if not revalidate:
            clauses.append("validation_status = '未验证'")
        sql = 'SELECT uri FROM "节点库"'
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rowid"
        rows = self.connection.execute(sql, params)
        for row in rows:
            yield row[0]

    def iter_asia_candidate_nodes(self, protocols: Sequence[str] = (), revalidate: bool = False) -> Iterator[str]:
        clauses = []
        params = []
        if protocols:
            placeholders = ",".join("?" for _ in protocols)
            clauses.append("protocol IN (" + placeholders + ")")
            params.extend(protocol.lower() for protocol in protocols)
        if not revalidate:
            clauses.append("validation_status = '未验证'")
        country_clauses = []
        for country in ASIA_COUNTRIES:
            country_clauses.append("UPPER(proxy_ips) LIKE ?")
            params.append("%" + country + "%")
        keyword_clauses = []
        for keyword in ASIA_KEYWORDS:
            keyword_clauses.extend(["LOWER(uri) LIKE ?", "LOWER(source) LIKE ?", "LOWER(repo) LIKE ?"])
            value = "%" + keyword.lower() + "%"
            params.extend([value, value, value])
        clauses.append("(" + " OR ".join(country_clauses + keyword_clauses) + ")")
        sql = 'SELECT uri FROM "节点库"'
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY validation_count ASC, rowid"
        rows = self.connection.execute(sql, params)
        for row in rows:
            yield row[0]

    def iter_valid_nodes_for_recheck(self, protocols: Sequence[str] = ()) -> Iterator[str]:
        clauses = []
        params = []
        if protocols:
            placeholders = ",".join("?" for _ in protocols)
            clauses.append("protocol IN (" + placeholders + ")")
            params.extend(protocol.lower() for protocol in protocols)
        sql = 'SELECT uri FROM "有效节点"'
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY last_validated ASC, validation_count ASC, seconds ASC, rowid ASC"
        rows = self.connection.execute(sql, params)
        for row in rows:
            yield row[0]

    def valid_asia_count(self) -> int:
        clauses = ["UPPER(country) LIKE ?" for _ in ASIA_COUNTRIES]
        params = ["%" + country + "%" for country in ASIA_COUNTRIES]
        return self.connection.execute(
            'SELECT COUNT(*) FROM "有效节点" WHERE ' + " OR ".join(clauses),
            params,
        ).fetchone()[0]

    def stats(self) -> Dict[str, object]:
        statuses = dict(self.connection.execute(
            'SELECT validation_status, COUNT(*) FROM "节点库" GROUP BY validation_status'
        ))
        valid_count = self.count("有效节点")
        invalid_count = self.counter("invalid_nodes_total") + self.counter("invalid_nodes_pruned")
        if valid_count:
            statuses["有效"] = valid_count
        if invalid_count:
            statuses["无效"] = invalid_count
        protocols = dict(self.connection.execute(
            'SELECT protocol, COUNT(*) FROM "节点库" GROUP BY protocol ORDER BY COUNT(*) DESC'
        ))
        countries = dict(self.connection.execute(
            'SELECT country, COUNT(*) FROM "有效节点" WHERE country != "" GROUP BY country ORDER BY COUNT(*) DESC'
        ))
        return {
            "total_nodes": self.count("节点库"),
            "valid_nodes": valid_count,
            "valid_asia_nodes": self.valid_asia_count(),
            "invalid_nodes": invalid_count,
            "duplicate_filtered": self.counter("duplicate_filtered"),
            "statuses": statuses,
            "protocols": protocols,
            "countries": countries,
        }

    def counter(self, key: str) -> int:
        row = self.connection.execute('SELECT value FROM "系统统计" WHERE key = ?', (key,)).fetchone()
        return row[0] if row else 0

    def auto_config_defaults(self) -> Dict[str, object]:
        return {
            "enabled": False,
            "valid_low_watermark": 20,
            "collect_insert_target": 200,
            "validate_valid_target": 20,
            "check_interval_minutes": 5,
            "collector_workers": 5,
            "collector_depth": 8,
            "collector_delay": 1.0,
            "collector_jitter": 0.5,
            "collector_log_level": "detail",
            "validator_workers": 10,
            "validator_rounds": 3,
            "validator_timeout": 8,
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

    def collector_repos(self, defaults: Sequence[str] = ()) -> List[str]:
        rows = [
            row[0] for row in self.connection.execute(
                'SELECT repo FROM "采集仓库" WHERE enabled = 1 ORDER BY sort_order, repo'
            )
        ]
        if rows:
            return rows
        return list(defaults)

    def replace_collector_repos(self, repos: Sequence[str]) -> None:
        self.connection.execute('DELETE FROM "采集仓库"')
        self.connection.executemany(
            """
            INSERT INTO "采集仓库" (repo, enabled, sort_order, created_at, updated_at)
            VALUES (?, 1, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            """,
            [(repo, index) for index, repo in enumerate(repos)],
        )
        self.connection.commit()

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

    def source_profiles(self, repo: str, limit: int = 200) -> Dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT source, node_count, success_count, fail_count
            FROM "采集来源画像"
            WHERE repo = ?
            ORDER BY node_count DESC, success_count DESC, source
            LIMIT ?
            """,
            (repo, limit),
        )
        return {
            source: max(0, int(node_count) + int(success_count) * 5 - int(fail_count) * 10)
            for source, node_count, success_count, fail_count in rows
        }

    def top_source_profiles(self, limit: int = 20) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT repo, source, node_count, success_count, fail_count, last_nodes, last_success, last_failure
            FROM "采集来源画像"
            ORDER BY node_count DESC, success_count DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "repo": row[0],
                "source": row[1],
                "node_count": row[2],
                "success_count": row[3],
                "fail_count": row[4],
                "last_nodes": row[5],
                "last_success": row[6],
                "last_failure": row[7],
            }
            for row in rows
        ]

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
        sql = 'SELECT COUNT(*) FROM "有效节点"'
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return self.connection.execute(sql, params).fetchone()[0]

    def valid_node_protocols(self) -> List[str]:
        return [
            row[0] for row in self.connection.execute(
                'SELECT protocol FROM "有效节点" GROUP BY protocol ORDER BY protocol'
            )
        ]

    def valid_node_countries(self) -> List[str]:
        countries = set()
        for row in self.connection.execute('SELECT country FROM "有效节点" WHERE country != ""'):
            for country in row[0].split(","):
                country = country.strip().upper()
                if country:
                    countries.add(country)
        return sorted(countries)

    def valid_nodes(self, limit: int = 50, offset: int = 0, protocol: str = "", country: str = "") -> List[Dict[str, object]]:
        clauses = []
        params = []
        if protocol:
            clauses.append("protocol = ?")
            params.append(protocol.lower())
        if country:
            clauses.append("country LIKE ?")
            params.append("%" + country.upper() + "%")
        sql = """
            SELECT uri, protocol, proxy_ips, seconds, last_validated, validation_count, country
            FROM "有效节点"
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += (
            "\n            ORDER BY "
            + asia_priority_sql()
            + ", seconds ASC, last_validated DESC, validation_count DESC, rowid DESC\n"
            "            LIMIT ? OFFSET ?\n"
        )
        params.extend([limit, offset])
        rows = self.connection.execute(
            sql,
            params,
        )
        return [
            {
                "uri": row[0],
                "protocol": row[1],
                "proxy_ips": row[2],
                "seconds": row[3],
                "last_validated": row[4],
                "validation_count": row[5],
                "country": row[6],
            }
            for row in rows
        ]

    def all_valid_nodes(self) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT uri, protocol, proxy_ips, seconds, last_validated, validation_count, country
            FROM "有效节点"
            ORDER BY """ + asia_priority_sql() + """, seconds ASC, last_validated DESC, validation_count DESC, rowid DESC
            """
        )
        return [
            {
                "uri": row[0],
                "protocol": row[1],
                "proxy_ips": row[2],
                "seconds": row[3],
                "last_validated": row[4],
                "validation_count": row[5],
                "country": row[6],
            }
            for row in rows
        ]

    def create_subscription_link(
        self,
        token: str,
        name: str,
        mode: str,
        max_uses: Optional[int] = None,
        expires_at: Optional[str] = None,
        rename_template: str = "",
        remark: str = "",
        claim_version: str = "",
        created_by: str = "manual",
        telegram_user_id: str = "",
        telegram_username: str = "",
    ) -> Dict[str, object]:
        if mode not in ("usage", "time", "either"):
            raise ValueError("unknown subscription mode: " + mode)
        self.connection.execute(
            """
            INSERT INTO "订阅链接" (
                token, name, mode, max_uses, expires_at, rename_template, remark,
                claim_version, created_by, telegram_user_id, telegram_username,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, BEIJING_TIMESTAMP(), BEIJING_TIMESTAMP())
            """,
            (
                token, name, mode, max_uses, expires_at, rename_template, remark,
                claim_version, created_by, telegram_user_id, telegram_username,
            ),
        )
        self.connection.commit()
        return self.subscription_link(token) or {}

    def subscription_link(self, token: str) -> Optional[Dict[str, object]]:
        row = self.connection.execute(
            """
            SELECT token, name, mode, enabled, max_uses, used_count, expires_at,
                   rename_template, remark, created_at, updated_at, last_used_at, last_used_ip,
                   claim_version, created_by, telegram_user_id, telegram_username
            FROM "订阅链接"
            WHERE token = ?
            """,
            (token,),
        ).fetchone()
        return self._subscription_row(row) if row else None

    def subscription_links(self, limit: int = 100) -> List[Dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT token, name, mode, enabled, max_uses, used_count, expires_at,
                   rename_template, remark, created_at, updated_at, last_used_at, last_used_ip,
                   claim_version, created_by, telegram_user_id, telegram_username
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
            "max_uses": row[4],
            "used_count": row[5],
            "expires_at": row[6],
            "rename_template": row[7],
            "remark": row[8],
            "created_at": row[9],
            "updated_at": row[10],
            "last_used_at": row[11],
            "last_used_ip": row[12],
            "claim_version": row[13],
            "created_by": row[14],
            "telegram_user_id": row[15],
            "telegram_username": row[16],
        }

    def claim_config_defaults(self) -> Dict[str, object]:
        return {
            "youtube_channel_url": "",
            "claim_code": "",
            "claim_version": "一期",
            "claim_expires_at": "",
            "daily_claim_limit": 1,
            "group_dm_success_message": "已私发你领取说明，请查收。",
            "group_dm_failed_message": "我还不能私发你。请先私聊机器人发送 /start，然后回群重新发送“我要节点”。",
            "claim_prompt_message": "请先订阅我的 YouTube 频道，并在最新的免费节点领取视频中找到本期领取口令。",
            "youtube_button_message": "请打开我的 YouTube 频道，观看最新的免费节点领取视频，并在视频中找到本期领取口令。",
            "ask_code_message": "请发送你在 YouTube 最新免费节点领取视频中看到的领取口令。",
            "wrong_code_message": "口令不正确，请回到 YouTube 频道，查看最新免费节点领取视频中的领取口令。",
            "expired_code_message": "本期领取口令已过期，请前往 YouTube 频道查看最新免费节点领取视频，获取新的领取口令。",
            "limit_message": "你今天已经领取过，请明天再来。",
            "success_message": "验证成功，下面是你的专属订阅链接。",
        }

    def claim_config(self) -> Dict[str, object]:
        config = self.claim_config_defaults()
        rows = dict(self.connection.execute('SELECT key, value FROM "领取口令配置"'))
        config.update({key: value for key, value in rows.items() if key in config})
        try:
            config["daily_claim_limit"] = max(1, min(int(config["daily_claim_limit"]), 100))
        except (TypeError, ValueError):
            config["daily_claim_limit"] = 1
        return config

    def update_claim_config(self, values: Dict[str, object]) -> Dict[str, object]:
        defaults = self.claim_config_defaults()
        current = self.claim_config()
        cleaned = {}
        for key in defaults:
            if key not in values:
                continue
            value = values[key]
            if key == "daily_claim_limit":
                value = max(1, min(int(value), 100))
            else:
                value = str(value).strip()
                if key == "youtube_channel_url" and value and not value.startswith(("http://", "https://")):
                    value = "https://" + value
            cleaned[key] = value
        if "claim_code" in cleaned:
            old_code = str(current.get("claim_code", ""))
            old_version = str(current.get("claim_version", ""))
            next_version = str(cleaned.get("claim_version", old_version))
            if cleaned["claim_code"] != old_code and next_version == old_version:
                cleaned["claim_version"] = "口令-" + self.connection.execute("SELECT strftime('%Y%m%d%H%M%S', 'now', '+8 hours')").fetchone()[0]
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
        return self.claim_config()

    def set_bot_claim_state(self, telegram_user_id: str, telegram_chat_id: str, username: str, state: str) -> None:
        self.connection.execute(
            """
            INSERT INTO "Bot领取状态" (telegram_user_id, telegram_chat_id, username, state, updated_at)
            VALUES (?, ?, ?, ?, BEIJING_TIMESTAMP())
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                telegram_chat_id = excluded.telegram_chat_id,
                username = excluded.username,
                state = excluded.state,
                updated_at = BEIJING_TIMESTAMP()
            """,
            (telegram_user_id, telegram_chat_id, username, state),
        )
        self.connection.commit()

    def bot_claim_state(self, telegram_user_id: str) -> Dict[str, object]:
        row = self.connection.execute(
            """
            SELECT telegram_user_id, telegram_chat_id, username, state, updated_at
            FROM "Bot领取状态"
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()
        if not row:
            return {}
        return {
            "telegram_user_id": row[0],
            "telegram_chat_id": row[1],
            "username": row[2],
            "state": row[3],
            "updated_at": row[4],
        }

    def clear_bot_claim_state(self, telegram_user_id: str) -> None:
        self.connection.execute('DELETE FROM "Bot领取状态" WHERE telegram_user_id = ?', (telegram_user_id,))
        self.connection.commit()

    def bot_claim_count_today(self, telegram_user_id: str, claim_version: str) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM "Bot领取记录"
            WHERE telegram_user_id = ?
              AND claim_version = ?
              AND date(created_at) = date(BEIJING_TIMESTAMP())
            """,
            (telegram_user_id, claim_version),
        ).fetchone()
        return int(row[0] or 0)

    def record_bot_claim(self, telegram_user_id: str, telegram_username: str, claim_version: str, subscription_token: str) -> None:
        self.connection.execute(
            """
            INSERT INTO "Bot领取记录" (telegram_user_id, telegram_username, claim_version, subscription_token, created_at)
            VALUES (?, ?, ?, ?, BEIJING_TIMESTAMP())
            """,
            (telegram_user_id, telegram_username, claim_version, subscription_token),
        )
        self.connection.commit()

    def bot_config_defaults(self) -> Dict[str, object]:
        return {
            "bot_token": "",
            "bot_username": "",
            "auto_run": False,
            "keywords": "节点\n订阅\nVMTOK",
            "reply_message": "测试回复：BOT 已成功监测到关键字。",
            "youtube_url": "",
            "youtube_channel_id": "",
            "public_base_url": "https://node.huage.us",
            "verify_link_minutes": 30,
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
        token = str(config["bot_token"])
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
            elif key == "auto_run":
                value = "1" if value is True or str(value).lower() in ("1", "true", "yes", "on") else "0"
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

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "NodeDatabase":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
