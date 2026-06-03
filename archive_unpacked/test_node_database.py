import sqlite3
import tempfile
import unittest
from pathlib import Path

from node_database import NodeDatabase


class NodeDatabaseTest(unittest.TestCase):
    def test_stores_crawled_and_valid_nodes_in_named_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.upsert_node("vless://uuid@example.com:443", "owner/repo", "nodes.txt", "plain")
                database.upsert_valid_node(
                    "vless://uuid@example.com:443",
                    "稳定代理检查通过: 3 轮; 出口 203.0.113.10",
                    1.25,
                    "203.0.113.10",
                )
                self.assertEqual(database.count("节点库"), 0)
                self.assertEqual(database.count("有效节点"), 1)
                self.assertEqual(database.stats()["valid_nodes"], 1)
                self.assertEqual(database.stats()["statuses"]["有效"], 1)
                self.assertEqual(database.valid_nodes()[0]["proxy_ips"], "203.0.113.10")
                self.assertEqual(list(database.iter_nodes()), [])
                self.assertEqual(list(database.iter_nodes(revalidate=True)), [])
                valid = database.connection.execute('SELECT protocol, seconds FROM "有效节点"').fetchone()
                self.assertEqual(valid, ("vless", 1.25))
                database.record_validation("vless://uuid@example.com:443", "无效", "expired", 2.5)
                self.assertEqual(database.count("有效节点"), 0)
                self.assertEqual(database.stats()["statuses"]["无效"], 1)

            connection = sqlite3.connect(path)
            row = connection.execute('SELECT value FROM "系统统计" WHERE key = "invalid_nodes_total"').fetchone()
            self.assertEqual(row, (1,))

    def test_counts_filtered_duplicates_without_storing_extra_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            node = ("ss://YWVzLTEyOC1nY206cHc@example.com:8388", "owner/repo", "nodes.txt", "plain")
            with NodeDatabase(path) as database:
                self.assertEqual(database.upsert_nodes([node, node]), 1)
                self.assertEqual(database.upsert_nodes([node]), 1)
                self.assertEqual(database.count("节点库"), 1)
                self.assertEqual(database.stats()["duplicate_filtered"], 2)

    def test_stores_collector_repositories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                self.assertEqual(database.collector_repos(["default/repo"]), ["default/repo"])
                database.replace_collector_repos(["owner/one", "owner/two"])
                self.assertEqual(database.collector_repos(["default/repo"]), ["owner/one", "owner/two"])

    def test_stores_source_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.record_source_result("owner/repo", "sub.txt", 10, True)
                database.record_source_result("owner/repo", "sub.txt", 5, True)
                database.record_source_result("owner/repo", "bad.txt", 0, False)
                self.assertGreater(database.source_profiles("owner/repo")["sub.txt"], 0)
                top = database.top_source_profiles()
                self.assertEqual(top[0]["source"], "sub.txt")
                self.assertEqual(top[0]["node_count"], 15)

    def test_verified_nodes_are_not_reinserted_into_pending_library(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            node = ("vless://uuid@example.com:443", "owner/repo", "nodes.txt", "plain")
            with NodeDatabase(path) as database:
                database.upsert_nodes([node])
                database.record_validation(node[0], "有效", "ok", 1.0)
                self.assertEqual(database.count("节点库"), 0)
                self.assertEqual(database.upsert_nodes([node]), 1)
                self.assertEqual(database.count("节点库"), 0)
                self.assertEqual(database.count("有效节点"), 1)

    def test_invalid_nodes_can_be_recollected_for_future_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            node = ("vless://uuid@example.com:443", "owner/repo", "nodes.txt", "plain")
            with NodeDatabase(path) as database:
                database.upsert_nodes([node])
                database.record_validation(node[0], "无效", "bad", 1.0)
                self.assertEqual(database.count("节点库"), 0)
                self.assertEqual(database.stats()["invalid_nodes"], 1)
                self.assertEqual(database.upsert_nodes([node]), 0)
                self.assertEqual(database.count("节点库"), 1)

    def test_manages_subscription_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                link = database.create_subscription_link(
                    "token123",
                    "测试订阅",
                    "usage",
                    max_uses=2,
                    rename_template="{protocol}",
                    remark="unit",
                )
                self.assertEqual(link["used_count"], 0)
                self.assertTrue(link["enabled"])
                database.touch_subscription_link("token123", "127.0.0.1")
                self.assertEqual(database.subscription_link("token123")["used_count"], 1)
                database.set_subscription_enabled("token123", False)
                self.assertFalse(database.subscription_link("token123")["enabled"])
                self.assertTrue(database.delete_subscription_link("token123"))
                self.assertIsNone(database.subscription_link("token123"))

    def test_stores_subscription_link_with_either_expiration_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                link = database.create_subscription_link(
                    "token-either",
                    "双条件订阅",
                    "either",
                    max_uses=5,
                    expires_at="2099-01-01 00:00:00",
                )
                self.assertEqual(link["mode"], "either")
                self.assertEqual(link["max_uses"], 5)
                self.assertEqual(link["expires_at"], "2099-01-01 00:00:00")

    def test_stores_bot_config_verification_and_message_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_bot_config({
                    "bot_token": "123456:secret-token",
                    "auto_run": True,
                    "keywords": "节点\n订阅",
                    "reply_message": "测试回复",
                    "verify_link_minutes": 45,
                })
                self.assertTrue(config["token_configured"])
                self.assertTrue(config["auto_run"])
                self.assertEqual(config["bot_token"], "123456...oken")
                self.assertEqual(config["verify_link_minutes"], 45)
                self.assertEqual(config["reply_message"], "测试回复")
                database.create_bot_verification(
                    "verify-token",
                    "user-1",
                    "chat-1",
                    "tester",
                    "2099-01-01 00:00:00",
                )
                self.assertEqual(database.bot_verification("verify-token")["status"], "待验证")
                database.record_bot_message("user-1", "chat-1", "收到", "节点")
                self.assertEqual(database.bot_message_logs()[0]["message"], "节点")
