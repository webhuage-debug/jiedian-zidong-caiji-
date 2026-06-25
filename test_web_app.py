import base64
import json
import unittest
import tempfile
import urllib.error
import urllib.parse
from http import HTTPStatus
from pathlib import Path

import web_app
from node_database import NodeDatabase
from web_app import ADMIN_BASE_PATH, DashboardHandler


class FakeBotTask:
    def __init__(self):
        self.started = []

    def status(self):
        return {"running": False, "pid": None, "started_at": None, "progress": {}}

    def start(self, command):
        self.started.append(command)
        return True


class FakeWorkerTask:
    def __init__(self):
        self.started = []
        self.stopped = 0
        self.running = False

    def status(self):
        return {"running": self.running, "pid": 123 if self.running else None, "started_at": 1 if self.running else None, "progress": {}}

    def start(self, command):
        self.started.append(command)
        self.running = True
        return True

    def stop(self):
        if not self.running:
            return False
        self.stopped += 1
        self.running = False
        return True

class FakeSubStoreResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b"converted-subscription"

    def getcode(self):
        return self.status


class WebAppRoutingTest(unittest.TestCase):
    def test_admin_route_maps_login_and_root_under_base_path(self):
        handler = object.__new__(DashboardHandler)
        self.assertEqual(handler.admin_route(ADMIN_BASE_PATH), "/")
        self.assertEqual(handler.admin_route(ADMIN_BASE_PATH + "/login"), "/login")
        self.assertEqual(handler.admin_route(ADMIN_BASE_PATH + "/styles.css"), "/styles.css")
        self.assertIsNone(handler.admin_route("/styles.css"))

    def test_subscription_either_mode_expires_when_any_condition_is_reached(self):
        handler = object.__new__(DashboardHandler)
        base = {"enabled": True, "mode": "either", "max_uses": 2, "used_count": 0, "expires_at": "2099-01-01 00:00:00"}
        self.assertTrue(handler.subscription_available(base)[0])
        by_usage = {**base, "used_count": 2}
        self.assertEqual(handler.subscription_available(by_usage)[1], HTTPStatus.GONE)
        by_time = {**base, "expires_at": "2000-01-01 00:00:00"}
        self.assertEqual(handler.subscription_available(by_time)[1], HTTPStatus.GONE)

    def test_subscription_claim_version_is_hard_gate(self):
        handler = object.__new__(DashboardHandler)
        claim_config = {
            "enabled": True,
            "version": "v2",
            "expires_at": "",
            "expired_message": "口令已更新",
        }
        link = {
            "enabled": True,
            "mode": "usage",
            "max_uses": 10,
            "used_count": 0,
            "claim_code_version": "v1",
        }
        available, status, reason = handler.subscription_available(link, claim_config, enforce_claim_version=True)
        self.assertFalse(available)
        self.assertEqual(status, HTTPStatus.GONE)
        self.assertEqual(reason, "口令已更新")

        current = {**link, "claim_code_version": "v2"}
        self.assertTrue(handler.subscription_available(current, claim_config, enforce_claim_version=True)[0])
        expired_claim = {**claim_config, "expires_at": "2000-01-01 00:00:00"}
        self.assertTrue(handler.subscription_available(current, expired_claim, enforce_claim_version=True)[0])

    def test_valid_recheck_validator_command_prefers_asia(self):
        command = web_app.build_validator_command({"valid_only": True, "prefer_asia": True, "limit": 25})
        self.assertIn("--valid-only", command)
        self.assertIn("--prefer-asia", command)
        self.assertIn("--limit", command)
        self.assertIn("25", command)
        self.assertNotIn("--random", command)

    def test_validator_command_only_randomizes_when_requested(self):
        ordered = web_app.build_validator_command({"limit": 25})
        randomized = web_app.build_validator_command({"limit": 25, "random": True})

        self.assertNotIn("--random", ordered)
        self.assertIn("--random", randomized)

    def test_system_health_summary_recommends_validation_when_pending_is_available(self):
        stats = {"valid_nodes": 7, "pending_nodes": 1000, "invalid_nodes": 0, "all_nodes": 1007}
        control = {"enabled": True, "config": {"valid_low_watermark": 1000}}
        tasks = {
            "collector": {"running": False},
            "validator": {"running": False},
        }
        summary = web_app.system_health_summary(stats, control, tasks)
        self.assertEqual(summary["status"], "需补货")
        self.assertEqual(summary["recommendation"], "优先验证")
        self.assertIn("有效节点严重不足", summary["risks"])

    def test_sub_store_converter_targets_and_lightweight_download_request(self):
        targets = {target["id"]: target["target"] for target in web_app.subscription_converter_targets()}
        self.assertEqual(targets["v2rayng"], "V2Ray")
        self.assertEqual(targets["clash-verge"], "ClashMeta")
        self.assertEqual(targets["sing-box"], "sing-box")
        self.assertEqual(targets["surge"], "Surge")
        self.assertEqual(targets["shadowrocket"], "Shadowrocket")

        captured = {"urls": []}
        original_urlopen = web_app.urllib.request.urlopen
        try:
            def fake_urlopen(request, timeout=0):
                captured["urls"].append(request.full_url)
                captured["timeout"] = timeout
                return FakeSubStoreResponse()

            web_app.urllib.request.urlopen = fake_urlopen
            result = web_app.convert_with_sub_store(
                {"backend_url": "http://127.0.0.1:3001", "profile_name": "sub"},
                "surge",
                "vless://uuid@example.com:443",
            )
        finally:
            web_app.urllib.request.urlopen = original_urlopen

        self.assertEqual(result["content"], "converted-subscription")
        download_urls = [url for url in captured["urls"] if "/download/" in url]
        self.assertEqual(len(download_urls), 1)
        self.assertIn("/download/sub-huage-", download_urls[0])
        self.assertIn("target=Surge", download_urls[0])
        self.assertNotIn("content=", download_urls[0])

    def test_subscription_converter_failure_is_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            original_urlopen = web_app.urllib.request.urlopen
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_subscription_converter_config({"backend_url": "http://sub-store:3001"})

                def failing_urlopen(request, timeout=0):
                    raise urllib.error.URLError("offline")

                web_app.urllib.request.urlopen = failing_urlopen
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.convert_subscription({
                    "target": "surge",
                    "input_mode": "custom",
                    "input_type": "vless",
                    "content": "vless://uuid@example.com:443",
                })

                self.assertEqual(responses[-1][1], HTTPStatus.BAD_GATEWAY)
                with NodeDatabase(database_path) as database:
                    log = database.subscription_converter_logs()[0]
                self.assertEqual(log["target_id"], "surge")
                self.assertEqual(log["input_type"], "vless")
                self.assertEqual(log["status"], "failed")
            finally:
                web_app.DATABASE = original_database
                web_app.urllib.request.urlopen = original_urlopen

    def test_subscription_converter_health_check_logs_result(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            original_urlopen = web_app.urllib.request.urlopen
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_subscription_converter_config({"backend_url": "http://sub-store:3001"})

                web_app.urllib.request.urlopen = lambda request, timeout=0: FakeSubStoreResponse()
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.check_subscription_converter_health({})

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertTrue(responses[-1][0]["health"]["ok"])
                with NodeDatabase(database_path) as database:
                    log = database.subscription_converter_logs()[0]
                self.assertEqual(log["target_id"], "health")
                self.assertEqual(log["status"], "success")
            finally:
                web_app.DATABASE = original_database
                web_app.urllib.request.urlopen = original_urlopen

    def test_bot_auto_run_starts_only_when_token_is_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            original_task = web_app.TASKS["bot"]
            fake_task = FakeBotTask()
            try:
                web_app.DATABASE = database_path
                web_app.TASKS["bot"] = fake_task
                with NodeDatabase(database_path) as database:
                    database.update_bot_config({"auto_run": True})
                self.assertFalse(web_app.ensure_bot_auto_run())
                self.assertEqual(fake_task.started, [])
                with NodeDatabase(database_path) as database:
                    database.update_bot_config({"bot_token": "123:token"})
                self.assertTrue(web_app.ensure_bot_auto_run())
                self.assertEqual(len(fake_task.started), 1)
            finally:
                web_app.DATABASE = original_database
                web_app.TASKS["bot"] = original_task

    def test_claim_code_redeem_enforces_version_and_daily_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_claim_code_config({
                        "code": "HUAGE",
                        "version": "v2",
                        "expires_at": "2099-01-01 00:00:00",
                        "daily_limit": 1,
                        "success_message": "领取成功",
                        "wrong_code_message": "口令错误",
                        "expired_message": "口令过期",
                        "limit_exceeded_message": "超过次数",
                    })
                handler = object.__new__(DashboardHandler)
                handler.headers = {}
                handler.client_address = ("127.0.0.1", 12345)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.redeem_claim_code({"code": "HUAGE", "version": "v1", "client_id": "tester"})
                self.assertEqual(responses[-1][1], HTTPStatus.GONE)
                self.assertEqual(responses[-1][0]["message"], "口令过期")

                handler.redeem_claim_code({"code": "HUAGE", "version": "v2", "client_id": "tester"})
                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertTrue(responses[-1][0]["ok"])

                handler.redeem_claim_code({"code": "HUAGE", "version": "v2", "client_id": "tester"})
                self.assertEqual(responses[-1][1], HTTPStatus.TOO_MANY_REQUESTS)
                self.assertEqual(responses[-1][0]["message"], "超过次数")

                with NodeDatabase(database_path) as database:
                    database.update_claim_code_config({"expires_at": "2000-01-01 00:00:00"})
                handler.redeem_claim_code({"code": "HUAGE", "version": "v2", "client_id": "another"})
                self.assertEqual(responses[-1][1], HTTPStatus.GONE)
                self.assertEqual(responses[-1][0]["status"], "expired")
            finally:
                web_app.DATABASE = original_database

    def test_subscription_submit_still_checks_claim_code_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_claim_code_config({
                        "code": "HUAGE",
                        "version": "v2",
                        "expires_at": "2000-01-01 00:00:00",
                        "daily_limit": 1,
                        "expired_message": "口令过期",
                    })
                    database.create_subscription_link("token-expired-claim", "测试订阅", "usage", max_uses=10)
                handler = object.__new__(DashboardHandler)
                handler.headers = {}
                handler.client_address = ("127.0.0.1", 12345)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))
                handler.send_text = lambda text, content_type, status=HTTPStatus.OK: responses.append(({"text": text}, status))

                handler.public_subscription_submit("/sub/token-expired-claim", {"code": "HUAGE", "client_id": "tester"})

                self.assertEqual(responses[-1][1], HTTPStatus.GONE)
                self.assertEqual(responses[-1][0]["status"], "expired")
                self.assertEqual(responses[-1][0]["error"], "口令过期")
            finally:
                web_app.DATABASE = original_database

    def test_public_subscription_get_outputs_client_content_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_claim_code_config({"version": "v-direct", "enabled": True})
                    database.create_subscription_link(
                        "direct-token",
                        "direct",
                        "usage",
                        max_uses=3,
                        expires_at=None,
                        rename_template="",
                        remark="",
                        export_limit=20,
                        claim_code_version="v-direct",
                    )
                handler = object.__new__(DashboardHandler)
                handler.path = "/sub/direct-token?target=clash-verge"
                handler.headers = {"User-Agent": "Clash Verge"}
                handler.client_address = ("127.0.0.1", 12345)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status, headers))
                handler.send_text = lambda text, content_type, status=HTTPStatus.OK: responses.append((text, content_type, status))
                handler.subscription_output = lambda database, link, claim_config, target_id: {
                    "target_id": target_id,
                    "target_name": "Clash Verge",
                    "content": "proxies:\n  - name: test\n",
                    "content_type": "text/yaml; charset=utf-8",
                    "count": 1,
                }

                handler.public_subscription("/sub/direct-token")

                self.assertEqual(responses[-1][1], "text/yaml; charset=utf-8")
                self.assertIn("proxies:", responses[-1][0])
                self.assertNotIn("<html", responses[-1][0].lower())
                with NodeDatabase(database_path) as database:
                    self.assertEqual(database.subscription_link("direct-token")["used_count"], 1)
            finally:
                web_app.DATABASE = original_database

    def test_public_subscription_base64_exports_publish_pool_uri(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                uri = "vless://55555555-5555-5555-5555-555555555555@public-cf.example.com:443?type=ws&security=tls#CF"
                with NodeDatabase(database_path) as database:
                    database.update_claim_code_config({"version": "v-pub", "enabled": True})
                    database.create_subscription_link(
                        "pub-token",
                        "public",
                        "usage",
                        max_uses=10,
                        export_limit=10,
                        claim_code_version="v-pub",
                    )
                    database.connection.execute(
                        """
                        INSERT INTO publish_subscription_pool (uri, protocol, server, port, manual_status, publish_enabled)
                        VALUES (?, 'vless', 'public-cf.example.com', '443', 'publishable', 1)
                        """,
                        (uri,),
                    )
                    database.connection.commit()
                handler = object.__new__(DashboardHandler)
                handler.path = "/sub/pub-token"
                handler.headers = {}
                handler.client_address = ("127.0.0.1", 12345)
                responses = []
                handler.send_text = lambda text, content_type, status=HTTPStatus.OK: responses.append((text, content_type, status))
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, "json", status))

                handler.public_subscription("/sub/pub-token")

                self.assertEqual(responses[-1][2], HTTPStatus.OK)
                self.assertEqual(responses[-1][1], "text/plain; charset=utf-8")
                decoded = base64.b64decode(responses[-1][0].strip()).decode("utf-8")
                self.assertIn("vless://", decoded)
                self.assertIn("public-cf.example.com", decoded)
                self.assertGreater(len(decoded.splitlines()), 0)
            finally:
                web_app.DATABASE = original_database

    def test_public_subscription_usage_limit_returns_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_claim_code_config({"version": "v-limit", "enabled": True})
                    database.create_subscription_link(
                        "limit-token",
                        "limit",
                        "usage",
                        max_uses=1,
                        export_limit=10,
                        claim_code_version="v-limit",
                    )
                    database.connection.execute('UPDATE "订阅链接" SET used_count = 1 WHERE token = ?', ("limit-token",))
                    database.connection.commit()
                handler = object.__new__(DashboardHandler)
                handler.path = "/sub/limit-token"
                handler.headers = {}
                handler.client_address = ("127.0.0.1", 12345)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.public_subscription("/sub/limit-token")

                self.assertEqual(responses[-1][1], HTTPStatus.GONE)
                self.assertIn("最大访问次数", responses[-1][0]["error"])
            finally:
                web_app.DATABASE = original_database

    def test_subscription_output_applies_final_region_filter_to_all_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            with NodeDatabase(database_path) as database:
                database.update_claim_code_config({"version": "v-filter", "enabled": True})
                link = database.create_subscription_link(
                    "filter-token",
                    "filter",
                    "usage",
                    export_limit=30,
                    claim_code_version="v-filter",
                )
                database.upsert_valid_node("vless://hk@example.com:443#Hong%20Kong", "ok", 0.2, "203.0.113.1", "HK")
                database.upsert_valid_node("vless://us@example.com:443#Los%20Angeles", "ok", 0.1, "203.0.113.2", "US")
                database.upsert_valid_node("vless://vn@example.com:443#Vietnam", "ok", 0.1, "203.0.113.3", "VN")
                database.upsert_valid_node("vless://uk@example.com:443#London", "ok", 0.05, "203.0.113.4", "GB")
                database.upsert_valid_node("vless://ru@example.com:443#Russia", "ok", 0.05, "203.0.113.5", "RU")
                database.upsert_valid_node("vless://ad@example.com:443#Telegram%20Channel", "ok", 0.05, "203.0.113.6", "HK")
                payload = base64.urlsafe_b64encode(
                    json.dumps({"ps": "unknown vmess", "add": "example.com", "port": "443", "id": "id"}).encode("utf-8")
                ).decode("ascii").rstrip("=")
                database.upsert_valid_node("vmess://" + payload, "ok", 0.05, "203.0.113.7", "")
                for uri in (
                    "vless://hk@example.com:443#Hong%20Kong",
                    "vless://us@example.com:443#Los%20Angeles",
                    "vless://vn@example.com:443#Vietnam",
                ):
                    database.mark_publish_node(uri, True)

                handler = object.__new__(DashboardHandler)
                claim_config = database.claim_code_config()

                raw = handler.subscription_output(database, link, claim_config, "raw")
                self.assertEqual(raw["count"], 3)
                self.assertIn("hk@example.com", raw["content"])
                self.assertIn("us@example.com", raw["content"])
                self.assertIn("vn@example.com", raw["content"])
                self.assertNotIn("uk@example.com", raw["content"])
                self.assertNotIn("ru@example.com", raw["content"])
                self.assertNotIn("ad@example.com", raw["content"])

                base64_result = handler.subscription_output(database, link, claim_config, "base64")
                decoded = base64.b64decode(base64_result["content"]).decode("utf-8")
                self.assertNotIn("uk@example.com", decoded)
                self.assertNotIn("ru@example.com", decoded)
                self.assertNotIn("ad@example.com", decoded)

                captured = {}
                original_convert = web_app.convert_with_sub_store
                try:
                    def fake_convert(config, target_id, content, timeout=25):
                        captured["content"] = content
                        return {
                            "target": "V2RayNG",
                            "content": content,
                            "bytes": len(content.encode("utf-8")),
                        }

                    web_app.convert_with_sub_store = fake_convert
                    converted = handler.subscription_output(database, link, claim_config, "v2rayng")
                finally:
                    web_app.convert_with_sub_store = original_convert

                self.assertEqual(converted["count"], 3)
                self.assertNotIn("uk@example.com", captured["content"])
                self.assertNotIn("ru@example.com", captured["content"])
                self.assertNotIn("ad@example.com", captured["content"])

    def test_subscription_conversion_empty_publish_pool_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            with NodeDatabase(database_path) as database:
                database.update_claim_code_config({"version": "v-empty", "enabled": True})
                link = database.create_subscription_link(
                    "empty-token",
                    "empty",
                    "usage",
                    export_limit=30,
                    claim_code_version="v-empty",
                )
                handler = object.__new__(DashboardHandler)

                with self.assertRaisesRegex(ValueError, "发布池没有可导出的节点"):
                    handler.subscription_output(database, link, database.claim_code_config(), "clash-verge")

    def test_subscription_converter_input_has_unique_node_names(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            with NodeDatabase(database_path) as database:
                database.update_claim_code_config({"version": "v-unique", "enabled": True})
                link = database.create_subscription_link(
                    "unique-token",
                    "unique",
                    "usage",
                    rename_template="free-nodes",
                    export_limit=30,
                    claim_code_version="v-unique",
                )
                for index, country in enumerate(["HK", "JP", "SG"], 1):
                    uri = "vless://same" + str(index) + "@example.com:443#old"
                    database.upsert_valid_node(
                        uri,
                        "ok",
                        0.1,
                        "203.0.113." + str(index),
                        country,
                    )
                    database.mark_publish_node(uri, True)

                captured = {}
                original_convert = web_app.convert_with_sub_store
                try:
                    def fake_convert(config, target_id, content, timeout=25):
                        captured["content"] = content
                        names = [
                            urllib.parse.unquote(urllib.parse.urlsplit(line).fragment)
                            for line in content.splitlines()
                            if line.strip()
                        ]
                        return {
                            "target": "Clash Verge",
                            "content": "proxies:\n" + "\n".join("  - name: " + name for name in names),
                            "bytes": len(content.encode("utf-8")),
                        }

                    web_app.convert_with_sub_store = fake_convert
                    handler = object.__new__(DashboardHandler)
                    result = handler.subscription_output(database, link, database.claim_code_config(), "clash-verge")
                finally:
                    web_app.convert_with_sub_store = original_convert

                names = [
                    urllib.parse.unquote(urllib.parse.urlsplit(line).fragment)
                    for line in captured["content"].splitlines()
                    if line.strip()
                ]
                self.assertEqual(names, ["free-nodes", "free-nodes #2", "free-nodes #3"])
                self.assertEqual(len(names), len(set(names)))
                self.assertIn("free-nodes #2", result["content"])

    def test_publish_pool_api_marks_candidate_for_final_output(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                uri = "vless://api-publish@example.com:443?type=ws&security=tls#Hong%20Kong"
                with NodeDatabase(database_path) as database:
                    database.upsert_valid_node(uri, "ok", 0.2, "203.0.113.40", "HK")
                    database.refresh_premium_subscription_pool(10)
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.mark_publish_pool({"uri": uri, "publishable": True})

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertEqual(responses[-1][0]["publish_count"], 1)
                with NodeDatabase(database_path) as database:
                    self.assertEqual(len(database.export_publish_subscription_nodes(10)), 1)
            finally:
                web_app.DATABASE = original_database

    def test_publish_center_api_returns_layered_counts_and_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                published_uri = "vless://11111111-1111-1111-1111-111111111111@api-published.example.com:443?type=ws&security=tls#HK"
                ready_uri = "vless://22222222-2222-2222-2222-222222222222@api-ready.example.com:443?type=ws&security=tls#JP"
                manual_cf_uri = "vless://33333333-3333-3333-3333-333333333333@api-cf.example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
                with NodeDatabase(database_path) as database:
                    database.upsert_valid_node(published_uri, "ok", 0.1, "203.0.113.60", "HK")
                    database.upsert_valid_node(ready_uri, "ok", 0.2, "203.0.113.61", "JP")
                    database.import_manual_valid_nodes(manual_cf_uri, "api cf", "manual_cf")
                    database.refresh_premium_subscription_pool(10)
                    database.mark_publish_node(published_uri, True)

                def call(path):
                    handler = object.__new__(DashboardHandler)
                    handler.path = ADMIN_BASE_PATH + path
                    handler.current_user = lambda: {"id": 1, "username": "admin"}
                    responses = []
                    handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))
                    handler.do_GET()
                    return responses[-1]

                summary, summary_status = call("/api/publish-center/summary")
                published, published_status = call("/api/publish-center/published")
                ready, ready_status = call("/api/publish-center/ready")

                self.assertEqual(summary_status, HTTPStatus.OK)
                self.assertEqual(published_status, HTTPStatus.OK)
                self.assertEqual(ready_status, HTTPStatus.OK)
                self.assertTrue(summary["ok"])
                self.assertEqual(summary["published_count"], 1)
                self.assertGreaterEqual(summary["ready_count"], 2)
                self.assertEqual(published["count"], summary["published_count"])
                self.assertEqual(ready["count"], summary["ready_count"])
                self.assertNotIn("uri", published["nodes"][0])
                self.assertNotIn("uri", ready["nodes"][0])
                self.assertTrue(published["nodes"][0]["node_ref"])
                ready_refs = {node["node_ref"] for node in ready["nodes"]}
                with NodeDatabase(database_path) as database:
                    self.assertIn(database.resolve_node_reference(next(iter(ready_refs))), {ready_uri, manual_cf_uri})

                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))
                ready_ref = next(node["node_ref"] for node in ready["nodes"] if node["server"] == "api-ready.example.com")
                handler.mark_publish_pool({"node_ref": ready_ref, "publishable": True})
                self.assertEqual(responses[-1][1], HTTPStatus.OK)

                summary_after, _ = call("/api/publish-center/summary")
                ready_after, _ = call("/api/publish-center/ready")
                self.assertEqual(summary_after["published_count"], 2)
                self.assertNotIn(ready_ref, {node["node_ref"] for node in ready_after["nodes"]})
            finally:
                web_app.DATABASE = original_database

    def test_manual_valid_node_api_imports_and_disable_clears_output_pools(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                uri = "vless://api-manual@example.com:443?type=ws&security=tls#HK"
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.import_manual_valid_nodes({"nodes": uri + "\nnot-a-node", "note": "manual"})

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertEqual(responses[-1][0]["result"]["added_count"], 1)
                self.assertEqual(responses[-1][0]["result"]["invalid_count"], 1)
                with NodeDatabase(database_path) as database:
                    self.assertEqual(database.publish_pool_count(), 0)
                    database.refresh_premium_subscription_pool(10)
                    database.mark_publish_node(uri, True)
                    self.assertEqual(database.publish_pool_count(), 1)

                handler.disable_valid_node({"uri": uri, "reason": "local bad"})

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertTrue(responses[-1][0]["result"]["conversion_cache_cleared"])
                with NodeDatabase(database_path) as database:
                    self.assertEqual(database.valid_node_count(), 0)
                    self.assertEqual(database.publish_pool_count(), 0)
            finally:
                web_app.DATABASE = original_database

    def test_manual_valid_node_api_imports_base64_subscription_without_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                uri = "vless://33333333-3333-3333-3333-333333333333@api-cf.example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
                encoded = base64.b64encode(uri.encode("utf-8")).decode("ascii").rstrip("=")
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.import_manual_valid_nodes({
                    "nodes": encoded,
                    "note": "华哥CF-API-Base64",
                    "source_type": "manual_cf",
                })

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertTrue(responses[-1][0]["ok"])
                self.assertEqual(responses[-1][0]["added_count"], 1)
                self.assertEqual(responses[-1][0]["base64_decoded_count"], 1)
                self.assertEqual(responses[-1][0]["extracted_count"], 1)
                self.assertEqual(responses[-1][0]["input_source_type"], "base64_text")
                with NodeDatabase(database_path) as database:
                    self.assertEqual(database.publish_pool_count(), 0)
                    rows = database.valid_nodes(10, group="manual_cf")
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["manual_note"], "华哥CF-API-Base64")
                    logs = database.manual_import_logs()
                    self.assertEqual(logs[0]["input_source_type"], "base64_text")
                    self.assertEqual(logs[0]["added_count"], 1)
            finally:
                web_app.DATABASE = original_database

    def test_status_includes_recent_manual_import_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                uri = "vless://44444444-4444-4444-4444-444444444444@status-cf.example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
                with NodeDatabase(database_path) as database:
                    database.import_manual_valid_nodes(uri + "\nnot-a-node", "status-note", "manual_cf")
                handler = object.__new__(DashboardHandler)

                status = handler.dashboard_status()

                logs = status["manual_import_logs"]
                self.assertGreaterEqual(len(logs), 1)
                self.assertEqual(logs[0]["input_source_type"], "raw_uri")
                self.assertEqual(logs[0]["selected_source_type"], "manual_cf")
                self.assertEqual(logs[0]["added_count"], 1)
                self.assertEqual(logs[0]["invalid_count"], 1)
                self.assertIn("unrecognized input", logs[0]["error_summary"])
            finally:
                web_app.DATABASE = original_database

    def test_valid_node_copy_api_returns_only_copyable_filtered_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                cf_uri = "vless://copy-cf@example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
                disabled_uri = "trojan://secret@disabled.example.com:443#SG"
                with NodeDatabase(database_path) as database:
                    database.import_manual_valid_nodes(cf_uri, "cf", "manual_cf")
                    database.import_manual_valid_nodes(disabled_uri, "normal", "manual_normal")
                    database.disable_valid_node(disabled_uri, "bad")
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.copy_valid_nodes({"group": "manual_cf"})

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertEqual(responses[-1][0]["count"], 1)
                self.assertIn(cf_uri, responses[-1][0]["content"])
                self.assertNotIn(disabled_uri, responses[-1][0]["content"])

                handler.copy_valid_nodes({"uri": disabled_uri})
                self.assertEqual(responses[-1][0]["count"], 0)
            finally:
                web_app.DATABASE = original_database

    def test_bot_simulation_uses_local_logic_without_telegram(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_bot_config({
                        "keywords": "节点",
                        "group_prompt_message": "请私聊领取",
                    })
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.simulate_bot_message({
                    "chat_type": "group",
                    "text": "节点",
                    "chat_id": "-100001",
                    "user_id": "200001",
                    "username": "tester",
                })

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                result = responses[-1][0]["result"]
                self.assertEqual(result["action"], "group_prompt")
                self.assertEqual(result["status"], "sent")
                self.assertEqual(result["replies"][0]["text"], "请私聊领取")
                with NodeDatabase(database_path) as database:
                    directions = [item["direction"] for item in database.bot_message_logs()]
                self.assertEqual(directions, ["模拟发送", "收到"])
            finally:
                web_app.DATABASE = original_database

    def test_bot_flow_simulation_runs_full_claim_path_and_cleans_subscription(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.update_claim_code_config({
                        "code": "FLOWCODE",
                        "version": "flow-v1",
                        "daily_limit": 5,
                        "success_message": "ok",
                        "wrong_code_message": "wrong",
                        "expired_message": "expired",
                        "limit_exceeded_message": "limited",
                    })
                    database.update_bot_config({
                        "bot_username": "@FlowBot",
                        "keywords": "我要节点",
                        "group_prompt_message": "点击按钮",
                        "private_instruction_message": "说明 {version}",
                        "subscription_card_message": "订阅 {subscription_url}",
                    })
                    uri = "vless://flow@example.com:443#Hong%20Kong"
                    database.upsert_valid_node(uri, "ok", 0.2, "203.0.113.30", "HK")
                    database.mark_publish_node(uri, True)
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.simulate_bot_flow({"user_id": "flow-user", "username": "flow-user", "group_chat_id": "-100001"})

                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                payload = responses[-1][0]
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["cleanup_deleted"])
                self.assertEqual([step["name"] for step in payload["steps"]], [
                    "群组关键词",
                    "私聊入口",
                    "口令领取",
                    "版本绑定",
                    "订阅入口安全",
                    "清理测试订阅",
                ])
                with NodeDatabase(database_path) as database:
                    self.assertEqual(database.subscription_links(), [])
            finally:
                web_app.DATABASE = original_database

    def test_repo_enable_disable_updates_enabled_collection_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            try:
                web_app.DATABASE = database_path
                with NodeDatabase(database_path) as database:
                    database.replace_collector_repos(["owner/one", "owner/two"])
                handler = object.__new__(DashboardHandler)
                responses = []
                handler.send_json = lambda payload, status=HTTPStatus.OK, headers=None: responses.append((payload, status))

                handler.set_repo_enabled("owner%2Fone", False)
                self.assertEqual(responses[-1][1], HTTPStatus.OK)
                self.assertEqual(responses[-1][0]["repos"], ["owner/two"])
                self.assertEqual(responses[-1][0]["count"], 1)

                handler.set_repo_enabled("owner%2Fone", True)
                self.assertEqual(responses[-1][0]["repos"], ["owner/one", "owner/two"])
            finally:
                web_app.DATABASE = original_database

    def test_manual_validation_request_goes_through_orchestrator(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nodes.db"
            original_database = web_app.DATABASE
            original_collector = web_app.TASKS["collector"]
            original_validator = web_app.TASKS["validator"]
            controller = web_app.AutoController(web_app.LOG_BUS)
            try:
                web_app.DATABASE = database_path
                web_app.TASKS["collector"] = FakeWorkerTask()
                web_app.TASKS["validator"] = FakeWorkerTask()
                with NodeDatabase(database_path) as database:
                    database.upsert_node("vless://uuid@example.com:443", "owner/repo", "nodes.txt", "plain")

                changed, reason = controller.request_validate({"limit": 1, "workers": 1, "rounds": 1, "timeout": 2})
                status = controller.status()

                self.assertTrue(changed)
                self.assertEqual(reason, "ok")
                self.assertEqual(status["mode"], "manual")
                self.assertEqual(status["intent"], "validate_pending")
                self.assertEqual(status["decision"], "start_validator")
                self.assertTrue(status["running"]["validator"])
                self.assertEqual(len(web_app.TASKS["validator"].started), 1)

                web_app.TASKS["validator"].running = False
                completed = controller.status()
                self.assertEqual(completed["phase"], "idle")
                self.assertEqual(completed["decision"], "worker_finished")
            finally:
                web_app.DATABASE = original_database
                web_app.TASKS["collector"] = original_collector
                web_app.TASKS["validator"] = original_validator

    def test_orchestrator_rejects_validator_when_collector_is_running(self):
        original_collector = web_app.TASKS["collector"]
        original_validator = web_app.TASKS["validator"]
        controller = web_app.AutoController(web_app.LOG_BUS)
        try:
            collector = FakeWorkerTask()
            collector.running = True
            web_app.TASKS["collector"] = collector
            web_app.TASKS["validator"] = FakeWorkerTask()

            changed, reason = controller.request_validate({"limit": 1, "workers": 1, "rounds": 1, "timeout": 2})

            self.assertFalse(changed)
            self.assertIn("总控拒绝验证", reason)
            self.assertEqual(web_app.TASKS["validator"].started, [])
        finally:
            web_app.TASKS["collector"] = original_collector
            web_app.TASKS["validator"] = original_validator


if __name__ == "__main__":
    unittest.main()
