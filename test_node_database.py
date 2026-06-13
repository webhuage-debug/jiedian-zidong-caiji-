import sqlite3
import tempfile
import unittest
import base64
import sqlite3
from pathlib import Path
from unittest.mock import patch

from node_collector import DEFAULT_REPOS
from node_database import NodeDatabase, classify_validation_failure, is_cf_candidate_uri


class NodeDatabaseTest(unittest.TestCase):
    def test_stores_crawled_and_valid_nodes_in_named_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.upsert_node("vless://uuid@example.com:443", "owner/repo", "nodes.txt", "plain")
                database.upsert_valid_node(
                    "vless://uuid@example.com:443",
                    "绋冲畾浠ｇ悊妫€鏌ラ€氳繃: 3 杞? 鍑哄彛 203.0.113.10",
                    1.25,
                    "203.0.113.10",
                )
                self.assertEqual(database.count("\u8282\u70b9\u5e93"), 0)
                self.assertEqual(database.count("\u6709\u6548\u8282\u70b9"), 1)
                self.assertEqual(database.stats()["valid_nodes"], 1)
                self.assertEqual(database.stats()["current_inventory_nodes"], 1)
                self.assertEqual(database.stats()["asset_nodes"], 1)
                self.assertEqual(database.stats()["statuses"]["\u6709\u6548"], 1)
                self.assertEqual(database.valid_nodes()[0]["proxy_ips"], "203.0.113.10")
                self.assertEqual(list(database.iter_nodes()), [])
                self.assertEqual(list(database.iter_nodes(revalidate=True)), [])
                valid = database.connection.execute('SELECT protocol, seconds FROM "\u6709\u6548\u8282\u70b9"').fetchone()
                self.assertEqual(valid, ("vless", 1.25))
                database.record_validation("vless://uuid@example.com:443", "\u65e0\u6548", "expired", 2.5)
                self.assertEqual(database.count("\u6709\u6548\u8282\u70b9"), 0)
                self.assertEqual(database.stats()["invalid_nodes"], 0)
                self.assertEqual(database.stats()["pending_nodes"], 0)
                self.assertEqual(database.stats()["all_nodes"], 0)
                self.assertEqual(database.stats()["current_inventory_nodes"], 0)
                self.assertEqual(database.stats()["historical_invalid_nodes"], 1)

            connection = sqlite3.connect(path)
            try:
                row = connection.execute('SELECT value FROM "\u7cfb\u7edf\u7edf\u8ba1" WHERE key = "invalid_nodes_total"').fetchone()
                self.assertEqual(row, (1,))
            finally:
                connection.close()

    def test_counts_filtered_duplicates_without_storing_extra_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            node = ("ss://YWVzLTEyOC1nY206cHc@example.com:8388", "owner/repo", "nodes.txt", "plain")
            with NodeDatabase(path) as database:
                self.assertEqual(database.upsert_nodes([node, node]), 1)
                self.assertEqual(database.upsert_nodes([node]), 1)
                self.assertEqual(database.count("\u8282\u70b9\u5e93"), 1)
                self.assertEqual(database.stats()["duplicate_filtered"], 2)

    def test_stores_collector_repositories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                self.assertEqual(database.collector_repos(["default/repo"]), ["default/repo"])
                database.replace_collector_repos(["owner/one", "owner/two"])
                self.assertEqual(database.collector_repos(["default/repo"]), ["owner/one", "owner/two"])
                items = database.collector_repo_items(["default/repo"])
                self.assertEqual(len(items), 2)
                self.assertTrue(items[0]["enabled"])
                database.set_collector_repo_enabled("owner/one", False)
                self.assertEqual(database.collector_repos(["default/repo"]), ["owner/two"])
                database.set_collector_repo_enabled("owner/two", False)
                self.assertEqual(database.collector_repos(["default/repo"]), [])
                database.set_collector_repo_enabled("owner/one", True)
                self.assertEqual(database.collector_repos(["default/repo"]), ["owner/one"])
                database.replace_collector_repos(["owner/one", "owner/two", "owner/three"])
                self.assertEqual(database.collector_repos(["default/repo"]), ["owner/one", "owner/three"])

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
                good_node = ("vless://uuid@example.com:443", "owner/repo", "sub.txt", "plain")
                bad_node = ("ss://YWVzLTEyOC1nY206cGFzc0@example.com:8388", "owner/repo", "bad.txt", "plain")
                database.upsert_nodes([good_node, bad_node])
                database.record_validation(good_node[0], "有效", "ok", 0.5, country="SG")
                database.record_validation(bad_node[0], "无效", "bad", 2.0)
                top = database.top_source_profiles()
                self.assertEqual(top[0]["source"], "sub.txt")
                self.assertEqual(top[0]["valid_count"], 1)
                self.assertEqual(top[0]["asia_valid_count"], 1)
                bad_profile = next(item for item in top if item["source"] == "bad.txt")
                self.assertEqual(bad_profile["invalid_count"], 1)

    def test_iter_nodes_prioritizes_supported_protocols_and_source_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.record_source_result("owner/repo", "good.txt", 500, True)
                database.record_source_result("owner/repo", "weak.txt", 1, True)
                nodes = [
                    ("vless://good@example.com:443", "owner/repo", "good.txt", "plain"),
                    ("vless://weak@example.com:443", "owner/repo", "weak.txt", "plain"),
                    ("hysteria2://fast@example.com:443", "owner/repo", "good.txt", "plain"),
                ]
                database.upsert_nodes(nodes)
                ordered = list(database.iter_nodes(revalidate=True))
                self.assertEqual(ordered[0], "vless://good@example.com:443")
                self.assertEqual(ordered[1], "vless://weak@example.com:443")
                self.assertEqual(ordered[2], "hysteria2://fast@example.com:443")

    def test_validation_failure_classification_and_source_cooldown(self):
        self.assertEqual(classify_validation_failure("curl: (28) Operation timed out"), "timeout")
        self.assertEqual(classify_validation_failure("unsupported by Xray: hysteria2"), "unsupported_protocol")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                weak_nodes = [
                    ("vless://weak" + str(index) + "@example.com:443", "owner/repo", "weak.txt", "plain")
                    for index in range(20)
                ]
                good_node = ("vless://good@example.com:443", "owner/repo", "good.txt", "plain")
                database.record_source_result("owner/repo", "weak.txt", 5000, True)
                database.record_source_result("owner/repo", "good.txt", 1, True)
                database.upsert_nodes(weak_nodes + [good_node])
                for node in weak_nodes:
                    database.record_validation(node[0], "无效", "curl: (28) Operation timed out", 1.0)
                profiles = database.top_source_profiles(10)
                weak = next(item for item in profiles if item["source"] == "weak.txt")
                self.assertTrue(weak["cooled_down"])
                self.assertEqual(weak["last_failure_category"], "timeout")
                self.assertEqual(list(database.iter_nodes(revalidate=True))[0], good_node[0])

    def test_records_validation_daily_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                good_node = ("vless://good@example.com:443", "owner/repo", "good.txt", "plain")
                bad_node = ("vless://bad@example.com:443", "owner/repo", "bad.txt", "plain")
                database.upsert_nodes([good_node, bad_node])
                database.record_validation(good_node[0], "有效", "ok", 0.2)
                database.record_validation(bad_node[0], "无效", "Connection refused", 0.3)
                rows = {
                    (item["category"], item["name"]): item["count"]
                    for item in database.daily_ops_stats(20)
                }
                self.assertEqual(rows[("validation", "valid")], 1)
                self.assertEqual(rows[("validation", "invalid")], 1)
                self.assertEqual(rows[("validation_failure", "connection_refused")], 1)

    def test_verified_nodes_are_not_reinserted_into_pending_library(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            node = ("vless://uuid@example.com:443", "owner/repo", "nodes.txt", "plain")
            with NodeDatabase(path) as database:
                database.upsert_nodes([node])
                database.record_validation(node[0], "\u6709\u6548", "ok", 1.0)
                self.assertEqual(database.count("\u8282\u70b9\u5e93"), 0)
                self.assertEqual(database.upsert_nodes([node]), 1)
                self.assertEqual(database.count("\u8282\u70b9\u5e93"), 0)
                self.assertEqual(database.count("\u6709\u6548\u8282\u70b9"), 1)

    def test_invalid_nodes_are_removed_and_can_be_recollected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            node = ("vless://uuid@example.com:443", "owner/repo", "nodes.txt", "plain")
            with NodeDatabase(path) as database:
                database.upsert_nodes([node])
                database.record_validation(node[0], "\u65e0\u6548", "bad", 1.0)
                self.assertEqual(database.count("\u8282\u70b9\u5e93"), 0)
                self.assertEqual(database.stats()["invalid_nodes"], 0)
                self.assertEqual(database.stats()["pending_nodes"], 0)
                self.assertEqual(database.stats()["all_nodes"], 0)
                stored = database.connection.execute('SELECT reason, validation_count FROM "\u65e0\u6548\u8282\u70b9" WHERE uri = ?', (node[0],)).fetchone()
                self.assertIsNone(stored)
                self.assertEqual(database.stats()["invalid_nodes_total"], 1)
                self.assertEqual(database.upsert_nodes([node]), 0)
                self.assertEqual(database.count("\u8282\u70b9\u5e93"), 1)
                self.assertEqual(database.stats()["pending_nodes"], 1)
                self.assertEqual(database.stats()["all_nodes"], 1)

    def test_manages_subscription_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                link = database.create_subscription_link(
                    "token123",
                    "娴嬭瘯璁㈤槄",
                    "usage",
                    max_uses=2,
                    rename_template="{protocol}",
                    remark="unit",
                )
                self.assertEqual(link["used_count"], 0)
                self.assertEqual(link["export_limit"], 30)
                self.assertEqual(link["claim_code_version"], "v1")
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
                    "either-link",
                    "either",
                    max_uses=5,
                    expires_at="2099-01-01 00:00:00",
                )
                self.assertEqual(link["mode"], "either")
                self.assertEqual(link["max_uses"], 5)
                self.assertEqual(link["expires_at"], "2099-01-01 00:00:00")

    def test_subscription_link_binds_current_claim_code_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.update_claim_code_config({"version": "v9"})
                link = database.create_subscription_link("token-version", "鐗堟湰璁㈤槄", "usage")
                self.assertEqual(link["claim_code_version"], "v9")

    def test_exports_valid_nodes_with_asia_priority_and_global_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.upsert_valid_node("vless://asia-slow@example.com:443", "ok", 3.0, "203.0.113.1", "JP")
                database.upsert_valid_node("vless://global-fast@example.com:443", "ok", 0.2, "203.0.113.2", "US")
                database.upsert_valid_node("vless://asia-fast@example.com:443", "ok", 0.1, "203.0.113.3", "SG")
                rows = database.export_valid_nodes(3, prefer_asia=True)
                self.assertEqual(rows[0]["uri"], "vless://asia-fast@example.com:443")
                self.assertEqual(rows[1]["uri"], "vless://global-fast@example.com:443")
                self.assertEqual(rows[2]["uri"], "vless://asia-slow@example.com:443")
                self.assertGreater(rows[0]["quality_score"], 0)

    def test_subscription_export_uses_premium_pool_default_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                nodes = []
                for index in range(35):
                    uri = "vless://node" + str(index) + "@example.com:443"
                    nodes.append((uri, "owner/repo", "nodes.txt", "plain"))
                slow_uri = "vless://slow@example.com:443"
                nodes.append((slow_uri, "owner/repo", "nodes.txt", "plain"))
                database.upsert_nodes(nodes)
                for index, node in enumerate(nodes[:-1]):
                    database.record_validation(
                        node[0],
                        "有效",
                        "ok",
                        0.1 + index * 0.01,
                        "203.0.113." + str(index),
                        "SG",
                    )
                database.record_validation(slow_uri, "有效", "slow", 5.0, "198.51.100.250", "US")

                rows = database.export_subscription_nodes(30, prefer_asia=True)
                self.assertEqual(len(rows), 30)
                self.assertNotIn(slow_uri, [row["uri"] for row in rows])
                self.assertEqual(database.stats()["premium_nodes"], 30)

    def test_subscription_pool_defaults_to_asia_then_us_and_excludes_other_regions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                samples = [
                    ("vless://jp-slower@example.com:443#Tokyo", 0.6, "203.0.113.10", "JP"),
                    ("vless://sg-dynamic@example.com:443#Singapore", 0.3, "203.0.113.11", ""),
                    ("vless://us-fast@example.com:443#Los%20Angeles", 0.1, "203.0.113.12", "US"),
                    ("vless://vn-filler@example.com:443#Vietnam", 0.05, "203.0.113.16", "VN"),
                    ("vless://gb-fast@example.com:443#London", 0.05, "203.0.113.13", "GB"),
                    ("vless://za-fast@example.com:443#South%20Africa", 0.05, "203.0.113.14", "ZA"),
                    ("vless://in-fast@example.com:443#India", 0.05, "203.0.113.17", "IN"),
                    ("vless://tg-ad@example.com:443#Telegram%20Channel", 0.05, "203.0.113.18", "HK"),
                    ("vless://unknown-fast@example.com:443#unknown", 0.05, "203.0.113.15", ""),
                ]
                for uri, seconds, proxy_ip, country in samples:
                    database.upsert_valid_node(uri, "ok", seconds, proxy_ip, country)

                rows = database.export_subscription_nodes(20, prefer_asia=True)
                uris = [row["uri"] for row in rows]

                self.assertEqual(uris[:2], [
                    "vless://sg-dynamic@example.com:443#Singapore",
                    "vless://jp-slower@example.com:443#Tokyo",
                ])
                self.assertIn("vless://us-fast@example.com:443#Los%20Angeles", uris)
                self.assertIn("vless://vn-filler@example.com:443#Vietnam", uris)
                self.assertNotIn("vless://gb-fast@example.com:443#London", uris)
                self.assertNotIn("vless://za-fast@example.com:443#South%20Africa", uris)
                self.assertNotIn("vless://in-fast@example.com:443#India", uris)
                self.assertNotIn("vless://tg-ad@example.com:443#Telegram%20Channel", uris)
                self.assertNotIn("vless://unknown-fast@example.com:443#unknown", uris)
                self.assertEqual(database.valid_node_count(), 9)

    def test_subscription_export_reuses_fresh_premium_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                nodes = []
                for index in range(25):
                    uri = "vless://cached" + str(index) + "@example.com:443"
                    nodes.append((uri, "owner/repo", "nodes.txt", "plain"))
                database.upsert_nodes(nodes)
                for index, node in enumerate(nodes):
                    database.record_validation(
                        node[0],
                        "\u6709\u6548",
                        "ok",
                        0.1 + index * 0.01,
                        "203.0.113." + str(index),
                        "SG",
                    )

                database.export_subscription_nodes(20, prefer_asia=True)
                database.connection.execute(
                    "UPDATE premium_subscription_pool SET reason = 'cached', updated_at = BEIJING_TIMESTAMP()"
                )
                database.connection.commit()

                rows = database.export_subscription_nodes(20, prefer_asia=True)
                self.assertEqual(len(rows), 20)
                self.assertTrue(all(row["premium_reason"] == "cached" for row in rows))

    def test_publish_pool_requires_manual_mark_and_filters_incompatible_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                publish_uri = "vless://publish@example.com:443?type=ws&security=tls#Hong%20Kong"
                candidate_only_uri = "vless://candidate@example.com:443?type=ws#Japan"
                database.upsert_valid_node(publish_uri, "ok", 0.2, "203.0.113.20", "HK")
                database.upsert_valid_node(candidate_only_uri, "ok", 0.1, "203.0.113.21", "JP")
                database.refresh_premium_subscription_pool(10)

                self.assertEqual(database.export_publish_subscription_nodes(10), [])
                overview = database.publish_pool_candidates()
                self.assertGreaterEqual(overview["candidate_count"], 2)

                database.mark_publish_node(publish_uri, True, "local ok")
                rows = database.export_publish_subscription_nodes(10)
                self.assertEqual([row["uri"] for row in rows], [publish_uri])
                self.assertEqual(database.stats()["publish_nodes"], 1)

                with self.assertRaises(ValueError):
                    database.mark_publish_node("vless://blocked@example.com:443?type=xhttp#Hong%20Kong", True)

                database.mark_publish_node(publish_uri, False)
                self.assertEqual(database.export_publish_subscription_nodes(10), [])

    def test_publish_pool_exports_enabled_uri_without_region_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            enabled_uri = "vless://11111111-1111-1111-1111-111111111111@cf-worker.example.com:443?type=ws&security=tls#CF"
            disabled_uri = "vless://22222222-2222-2222-2222-222222222222@disabled.example.com:443?type=ws&security=tls#Disabled"
            removed_uri = "vless://33333333-3333-3333-3333-333333333333@removed.example.com:443?type=ws&security=tls#Removed"
            with NodeDatabase(path) as database:
                database.connection.execute(
                    """
                    INSERT INTO publish_subscription_pool (uri, protocol, server, port, manual_status, publish_enabled)
                    VALUES (?, 'vless', 'cf-worker.example.com', '443', 'publishable', 1)
                    """,
                    (enabled_uri,),
                )
                database.connection.execute(
                    """
                    INSERT INTO publish_subscription_pool (uri, protocol, server, port, manual_status, publish_enabled)
                    VALUES (?, 'vless', 'disabled.example.com', '443', 'publishable', 0)
                    """,
                    (disabled_uri,),
                )
                database.upsert_valid_node(removed_uri, "ok", 0.1, "203.0.113.9", "")
                database.mark_publish_node(removed_uri, True)
                database.disable_valid_node(removed_uri, "manual bad")

                rows = database.export_publish_subscription_nodes(10)

                self.assertEqual([row["uri"] for row in rows], [enabled_uri])
                self.assertEqual(database.publish_pool_count(), 1)

    def test_publish_center_summary_published_and_ready_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            published_uri = "vless://11111111-1111-1111-1111-111111111111@published.example.com:443?type=ws&security=tls#HK"
            premium_ready_uri = "vless://22222222-2222-2222-2222-222222222222@ready.example.com:443?type=ws&security=tls#JP"
            manual_cf_uri = "vless://33333333-3333-3333-3333-333333333333@cf.example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
            disabled_uri = "trojan://secret@disabled.example.com:443#SG"
            with NodeDatabase(path) as database:
                database.upsert_valid_node(published_uri, "ok", 0.1, "203.0.113.10", "HK")
                database.upsert_valid_node(premium_ready_uri, "ok", 0.2, "203.0.113.11", "JP")
                database.import_manual_valid_nodes(manual_cf_uri, "manual cf", "manual_cf")
                database.upsert_valid_node(disabled_uri, "ok", 0.3, "203.0.113.12", "SG")
                database.refresh_premium_subscription_pool(10)
                database.mark_publish_node(published_uri, True)
                database.disable_valid_node(disabled_uri, "manual bad")

                summary = database.publish_center_summary()
                published = database.publish_center_published()
                ready = database.publish_center_ready()

                self.assertEqual(summary["published_count"], 1)
                self.assertEqual(summary["valid_count"], 3)
                self.assertEqual(summary["manual_cf_count"], 1)
                self.assertEqual(summary["cf_candidate_count"], 1)
                self.assertGreaterEqual(summary["ready_count"], 2)
                self.assertEqual([row["uri"] for row in published], [published_uri])
                ready_uris = {row["uri"] for row in ready}
                self.assertIn(premium_ready_uri, ready_uris)
                self.assertIn(manual_cf_uri, ready_uris)
                self.assertNotIn(published_uri, ready_uris)
                self.assertNotIn(disabled_uri, ready_uris)

    def test_manual_import_valid_nodes_deduplicates_and_rejects_bad_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                text = "\n".join([
                    "vless://manual-uuid@example.com:443?type=ws&security=tls#HK",
                    "vless://manual-uuid@example.com:443?security=tls&type=ws#same-node",
                    "not-a-node",
                    "trojan://secret@trojan.example.com:443#SG",
                ])
                result = database.import_manual_valid_nodes(text, "local test")

                self.assertEqual(result["added_count"], 2)
                self.assertEqual(result["duplicate_count"], 1)
                self.assertEqual(result["invalid_count"], 1)
                self.assertEqual(result["input_source_type"], "raw_uri")
                rows = database.valid_nodes(10)
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row["manual_added"] for row in rows))
                self.assertTrue(all(row["source_type"] == "manual_normal" for row in rows))
                self.assertEqual(database.export_publish_subscription_nodes(10), [])

    def test_manual_import_decodes_base64_subscription_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            vless = "vless://11111111-1111-1111-1111-111111111111@hk.example.com:443?type=ws&security=tls#HK"
            trojan = "trojan://secret@sg.example.com:443#SG"
            encoded = base64.urlsafe_b64encode((vless + "\n" + trojan).encode("utf-8")).decode("ascii").rstrip("=")
            with NodeDatabase(path) as database:
                result = database.import_manual_valid_nodes(encoded, "华哥CF-Base64", "manual_cf")

                self.assertEqual(result["added_count"], 2)
                self.assertEqual(result["duplicate_count"], 0)
                self.assertEqual(result["invalid_count"], 0)
                self.assertEqual(result["base64_decoded_count"], 1)
                self.assertEqual(result["subscription_url_count"], 0)
                self.assertEqual(result["extracted_count"], 2)
                self.assertEqual(result["input_source_type"], "base64_text")
                rows = database.valid_nodes(10, group="manual_cf")
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row["manual_note"] == "华哥CF-Base64" for row in rows))
                self.assertEqual(database.publish_pool_count(), 0)
                logs = database.manual_import_logs()
                self.assertEqual(len(logs), 1)
                self.assertEqual(logs[0]["input_source_type"], "base64_text")
                self.assertEqual(logs[0]["added_count"], 2)
                self.assertEqual(logs[0]["manual_note"], "华哥CF-Base64")

    def test_manual_import_fetches_subscription_url_and_redacts_invalid_url_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            vless = "vless://22222222-2222-2222-2222-222222222222@cf.example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
            encoded = base64.b64encode(vless.encode("utf-8")).decode("ascii")
            url = "https://example.com/sub?token=not-real-secret-token-123456&b64"
            with NodeDatabase(path) as database:
                with patch("node_database.fetch_subscription_url", return_value=encoded) as mocked_fetch:
                    result = database.import_manual_valid_nodes(url, "华哥CF-订阅测试01", "manual_cf")

                mocked_fetch.assert_called_once_with(url)
                self.assertEqual(result["added_count"], 1)
                self.assertEqual(result["subscription_url_count"], 1)
                self.assertEqual(result["base64_decoded_count"], 1)
                self.assertEqual(result["extracted_count"], 1)
                self.assertEqual(result["input_source_type"], "subscription_url")
                self.assertEqual(database.publish_pool_count(), 0)
                self.assertEqual(database.valid_nodes(10, group="manual_cf")[0]["manual_note"], "华哥CF-订阅测试01")

                blocked = database.import_manual_valid_nodes(
                    "http://127.0.0.1/sub?token=not-real-secret-token-123456",
                    "blocked",
                    "manual_cf",
                )
                self.assertEqual(blocked["added_count"], 0)
                self.assertEqual(blocked["invalid_count"], 1)
                self.assertEqual(blocked["subscription_url_count"], 1)
                self.assertNotIn("not-real-secret-token-123456", str(blocked))
                self.assertIn("token=%2A%2A%2A", str(blocked))
                logs = database.manual_import_logs(5)
                self.assertEqual(logs[0]["input_source_type"], "subscription_url")
                self.assertEqual(logs[0]["invalid_count"], 1)
                self.assertIn("subscription url host is not allowed", logs[0]["error_summary"])
                self.assertNotIn("not-real-secret-token-123456", str(logs))

    def test_manual_disable_removes_premium_publish_cache_and_blocks_revalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            uri = "vless://disable-me@example.com:443?type=ws&security=tls#HK"
            with NodeDatabase(path) as database:
                database.upsert_valid_node(uri, "ok", 0.1, "203.0.113.50", "HK")
                database.refresh_premium_subscription_pool(10)
                database.mark_publish_node(uri, True)
                database.subscription_conversion_cache_put({
                    "cache_key": "cache-disable",
                    "claim_code_version": "v1",
                    "target_id": "clash-verge",
                    "target_name": "Clash Verge",
                    "node_hash": "hash",
                    "input_mode": "subscription_link",
                    "input_type": "mixed",
                    "export_limit": 10,
                    "prefer_asia": True,
                    "backend_url": "http://127.0.0.1:3001",
                    "profile_name": "sub",
                    "content": "old",
                    "output_bytes": 3,
                })

                result = database.disable_valid_node(uri, "bad local test")

                self.assertTrue(result["removed_from_premium_pool"])
                self.assertTrue(result["removed_from_publish_pool"])
                self.assertTrue(result["conversion_cache_cleared"])
                self.assertEqual(database.valid_node_count(), 0)
                self.assertEqual(database.publish_pool_count(), 0)
                self.assertEqual(database.subscription_conversion_cache_stats()["rows"], 0)

                database.upsert_node(uri, "owner/repo", "nodes.txt", "plain")
                database.record_validation(uri, "有效", "ok again", 0.1, "203.0.113.50", "HK")
                self.assertEqual(database.valid_node_count(), 0)
                self.assertEqual(database.export_subscription_nodes(10), [])

    def test_manual_delete_removes_valid_premium_publish_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            uri = "trojan://secret@delete-me.example.com:443#SG"
            with NodeDatabase(path) as database:
                database.upsert_valid_node(uri, "ok", 0.1, "203.0.113.51", "SG")
                database.refresh_premium_subscription_pool(10)
                database.mark_publish_node(uri, True)
                result = database.delete_valid_node(uri, "manual delete")

                self.assertTrue(result["deleted"])
                self.assertEqual(database.valid_node_count(), 0)
                self.assertEqual(database.publish_pool_count(), 0)
                self.assertEqual(database.connection.execute("SELECT COUNT(*) FROM premium_subscription_pool").fetchone()[0], 0)

    def test_cf_candidate_sources_are_added_and_marked_without_auto_publish(self):
        self.assertIn("Surfboardv2ray/v2ray-worker-sub", DEFAULT_REPOS)
        self.assertTrue(is_cf_candidate_uri("vless://uuid@example.com:443?host=demo.pages.dev&type=ws#CF"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            uri = "vless://cf-uuid@worker.example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
            with NodeDatabase(path) as database:
                database.upsert_node(uri, "Surfboardv2ray/v2ray-worker-sub", "sub.txt", "plain")
                database.record_validation(uri, "有效", "ok", 0.1, "203.0.113.52", "HK")
                row = database.valid_nodes(1)[0]
                self.assertTrue(row["cf_candidate"])
                database.refresh_premium_subscription_pool(10)
                self.assertEqual(database.publish_pool_count(), 0)

    def test_manual_cf_import_filter_and_copy_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            cf_uri = "vless://manual-cf@example.com:443?type=ws&host=demo.workers.dev&security=tls#CF"
            normal_uri = "trojan://secret@normal.example.com:443#SG"
            with NodeDatabase(path) as database:
                cf_result = database.import_manual_valid_nodes(cf_uri, "华哥CF-20260612", "manual_cf")
                normal_result = database.import_manual_valid_nodes(normal_uri, "normal", "manual_normal")

                self.assertEqual(cf_result["added_count"], 1)
                self.assertEqual(normal_result["added_count"], 1)
                cf_rows = database.valid_nodes(20, group="manual_cf")
                normal_rows = database.valid_nodes(20, group="manual_normal")
                self.assertEqual([row["uri"] for row in cf_rows], [cf_uri])
                self.assertEqual([row["uri"] for row in normal_rows], [normal_uri])
                self.assertTrue(cf_rows[0]["cf_candidate"])
                self.assertEqual(cf_rows[0]["source_type"], "manual_cf")
                self.assertEqual(database.copyable_valid_node_uris(group="manual_cf"), [cf_uri])

                database.mark_publish_node(cf_uri, True)
                self.assertEqual(database.valid_node_count(group="published"), 1)
                self.assertEqual(database.valid_node_count(group="unpublished"), 1)

                database.disable_valid_node(cf_uri, "local bad")
                self.assertEqual(database.copyable_valid_node_uris(uri=cf_uri), [])
                self.assertEqual(database.copyable_valid_node_uris(group="disabled"), [])

    def test_stores_bot_config_verification_and_message_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_bot_config({
                    "bot_token": "123456:secret-token",
                    "auto_run": True,
                    "keywords": "鑺傜偣\n璁㈤槄",
                    "group_prompt_message": "璇风鑱?BOT 棰嗗彇鑺傜偣",
                    "verify_link_minutes": 45,
                })
                self.assertTrue(config["token_configured"])
                self.assertTrue(config["auto_run"])
                self.assertEqual(config["bot_token"], "123456...oken")
                self.assertEqual(config["verify_link_minutes"], 45)
                self.assertEqual(config["group_prompt_message"], "璇风鑱?BOT 棰嗗彇鑺傜偣")
                database.create_bot_verification(
                    "verify-token",
                    "user-1",
                    "chat-1",
                    "tester",
                    "2099-01-01 00:00:00",
                )
                self.assertEqual(database.bot_verification("verify-token")["status"], "\u5f85\u9a8c\u8bc1")
                database.record_bot_message("user-1", "chat-1", "in", "node")
                self.assertEqual(database.bot_message_logs()[0]["message"], "node")

    def test_stores_bot_youtube_lightweight_guide_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_bot_config({
                    "youtube_channel_url": "https://youtube.com/@huage",
                    "latest_free_node_video_url": "https://youtube.com/watch?v=free",
                    "youtube_guide_message": "watch {latest_free_node_video_url}",
                })
                self.assertEqual(config["youtube_channel_url"], "https://youtube.com/@huage")
                self.assertEqual(config["latest_free_node_video_url"], "https://youtube.com/watch?v=free")
                self.assertEqual(config["youtube_guide_message"], "watch {latest_free_node_video_url}")

    def test_stores_claim_code_config_and_daily_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_claim_code_config({
                    "enabled": True,
                    "code": "HUAGE2026",
                    "version": "v2",
                    "expires_at": "2099-01-01 00:00:00",
                    "daily_limit": 3,
                    "success_message": "ok",
                    "wrong_code_message": "wrong",
                    "expired_message": "expired",
                    "limit_exceeded_message": "limited",
                })
                self.assertTrue(config["enabled"])
                self.assertEqual(config["code"], "HUAGE2026")
                self.assertEqual(config["version"], "v2")
                self.assertEqual(config["expires_at"], "2099-01-01 00:00:00")
                self.assertEqual(config["daily_limit"], 3)
                database.record_claim_attempt("2026-06-04", "client-a", "v2", "HUAGE2026", "success", "127.0.0.1")
                database.record_claim_attempt("2026-06-04", "client-a", "v2", "BAD", "wrong_code", "127.0.0.1")
                self.assertEqual(database.claim_success_count("2026-06-04", "client-a", "v2"), 1)

    def test_stores_subscription_converter_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                defaults = database.subscription_converter_config()
                self.assertEqual(defaults["backend_url"], "http://127.0.0.1:3001")
                self.assertEqual(defaults["profile_name"], "sub")
                self.assertEqual(defaults["export_limit"], 30)
                self.assertTrue(defaults["prefer_asia"])

                config = database.update_subscription_converter_config({
                    "backend_url": "http://sub-store:3001/",
                    "profile_name": "mobile",
                    "export_limit": 250,
                    "prefer_asia": False,
                })
                self.assertEqual(config["backend_url"], "http://sub-store:3001/")
                self.assertEqual(config["profile_name"], "mobile")
                self.assertEqual(config["export_limit"], 80)
                self.assertFalse(config["prefer_asia"])
                database.record_subscription_converter_log(
                    "surge",
                    "Surge",
                    "custom",
                    "vless",
                    2,
                    128,
                    256,
                    "success",
                    "ok",
                )
                logs = database.subscription_converter_logs()
                self.assertEqual(logs[0]["target_id"], "surge")
                self.assertEqual(logs[0]["input_type"], "vless")
                self.assertEqual(logs[0]["status"], "success")

    def test_subscription_converter_defaults_can_use_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with patch.dict("os.environ", {
                "HUAGE_SUB_STORE_URL": "http://sub-store:3001",
                "HUAGE_SUB_STORE_PROFILE": "docker-sub",
            }):
                with NodeDatabase(path) as database:
                    defaults = database.subscription_converter_config()
            self.assertEqual(defaults["backend_url"], "http://sub-store:3001")
            self.assertEqual(defaults["profile_name"], "docker-sub")

    def test_subscription_converter_upgrades_old_local_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with patch.dict("os.environ", {}, clear=True):
                with NodeDatabase(path) as database:
                    database.update_subscription_converter_config({"backend_url": "http://127.0.0.1:3000"})
                    config = database.subscription_converter_config()
            self.assertEqual(config["backend_url"], "http://127.0.0.1:3001")

    def test_records_subscription_access_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.maintenance_config()
                self.assertTrue(config["enabled"])
                self.assertEqual(config["subscription_access_max_rows"], 10000)

                database.record_subscription_access("2026-06-05", "tok", "success", "iphash", "uahash", 3, 120, "ok")
                summary = database.connection.execute(
                    'SELECT count, node_count, latency_total_ms, latency_max_ms FROM "\u8ba2\u9605\u8bbf\u95ee\u6c47\u603b" WHERE token = ? AND status = ?',
                    ("tok", "success"),
                ).fetchone()
                self.assertEqual(summary, (1, 3, 120, 120))

                database.connection.execute(
                    """
                    INSERT INTO "\u8ba2\u9605\u8f6c\u6362\u65e5\u5fd7" (
                        target_id, target_name, input_mode, input_type, node_count,
                        input_bytes, output_bytes, status, message, created_at
                    ) VALUES ('surge', 'Surge', 'custom', 'vless', 1, 1, 0, 'failed', 'old', '2000-01-01 00:00:00')
                    """
                )
                database.connection.execute(
                    """
                    INSERT INTO "Bot\u6d88\u606f\u65e5\u5fd7" (
                        telegram_user_id, telegram_chat_id, direction, message, created_at
                    ) VALUES ('u', 'c', 'in', 'old', '2000-01-01 00:00:00')
                    """
                )
                database.connection.execute(
                    """
                    INSERT INTO "\u8ba2\u9605\u8bbf\u95ee\u65e5\u5fd7" (
                        access_date, token, status, ip_hash, user_agent_hash, node_count, latency_ms, message, created_at
                    ) VALUES ('2000-01-01', 'old', 'success', 'ip', 'ua', 0, 0, 'old', '2000-01-01 00:00:00')
                    """
                )
                database.connection.commit()

                result = database.run_maintenance_cleanup("test", {
                    **database.maintenance_config(),
                    "converter_log_days": 1,
                    "bot_log_days": 1,
                    "subscription_access_days": 1,
                    "converter_log_max_rows": 5000,
                    "bot_log_max_rows": 10000,
                    "subscription_access_max_rows": 20000,
                })
                self.assertGreaterEqual(result["deleted_rows"], 3)
                overview = database.maintenance_overview()
                self.assertIsNotNone(overview["last_cleanup"])
                self.assertEqual(overview["table_counts"]["\u8ba2\u9605\u8bbf\u95ee\u65e5\u5fd7"], 1)

    def test_cleanup_stale_unvalidated_nodes_removes_old_nodes_and_premium_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.connection.execute(
                    'INSERT INTO "节点库" (uri, protocol, repo, source, first_seen, last_seen) '
                    'VALUES (?, ?, ?, ?, datetime(BEIJING_TIMESTAMP(), ?), datetime(BEIJING_TIMESTAMP(), ?))',
                    ("vless://pending-old@example.com:443", "vless", "owner/repo", "nodes.txt", "-4 days", "-4 days"),
                )
                database.connection.execute(
                    'INSERT INTO "节点库" (uri, protocol, repo, source) VALUES (?, ?, ?, ?)',
                    ("vless://pending-new@example.com:443", "vless", "owner/repo", "nodes.txt"),
                )
                database.connection.execute(
                    'INSERT INTO "有效节点" (uri, protocol, last_validated) VALUES (?, ?, datetime(BEIJING_TIMESTAMP(), ?))',
                    ("vless://valid-old@example.com:443", "vless", "-4 days"),
                )
                database.connection.execute(
                    'INSERT INTO "有效节点" (uri, protocol) VALUES (?, ?)',
                    ("vless://valid-new@example.com:443", "vless"),
                )
                database.connection.execute(
                    "INSERT INTO premium_subscription_pool (uri, score, reason, updated_at) VALUES (?, 1, ?, BEIJING_TIMESTAMP())",
                    ("vless://valid-old@example.com:443", "test"),
                )
                database.connection.commit()

                result = database.cleanup_stale_unvalidated_nodes(3)

                self.assertEqual(result["待验证节点_超过天数未验证"], 1)
                self.assertEqual(result["有效节点_超过天数未验证"], 1)
                self.assertEqual(result["订阅候选池_同步删除"], 1)
                self.assertEqual(database.connection.execute('SELECT COUNT(*) FROM "节点库" WHERE uri = ?', ("vless://pending-old@example.com:443",)).fetchone()[0], 0)
                self.assertEqual(database.connection.execute('SELECT COUNT(*) FROM "节点库" WHERE uri = ?', ("vless://pending-new@example.com:443",)).fetchone()[0], 1)
                self.assertEqual(database.connection.execute('SELECT COUNT(*) FROM "有效节点" WHERE uri = ?', ("vless://valid-old@example.com:443",)).fetchone()[0], 0)
                self.assertEqual(database.connection.execute('SELECT COUNT(*) FROM "有效节点" WHERE uri = ?', ("vless://valid-new@example.com:443",)).fetchone()[0], 1)
                self.assertEqual(database.connection.execute("SELECT COUNT(*) FROM premium_subscription_pool WHERE uri = ?", ("vless://valid-old@example.com:443",)).fetchone()[0], 0)

    def test_migrates_old_long_run_maintenance_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.update_maintenance_config({
                    "bot_log_max_rows": 10000,
                    "subscription_access_max_rows": 20000,
                    "maintenance_record_days": 180,
                    "acceptance_report_max_files": 300,
                })
                database.connection.execute('DELETE FROM "系统统计" WHERE key = ?', ("long_run_defaults_v2",))
                database.connection.commit()

            with NodeDatabase(path) as database:
                config = database.maintenance_config()
                self.assertEqual(config["bot_log_max_rows"], 5000)
                self.assertEqual(config["subscription_access_max_rows"], 10000)
                self.assertEqual(config["maintenance_record_days"], 30)
                self.assertEqual(config["acceptance_report_max_files"], 120)

    def test_stale_unvalidated_default_is_two_days_and_migrates_old_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                self.assertEqual(database.maintenance_config()["stale_unvalidated_node_days"], 2)
                database.update_maintenance_config({"stale_unvalidated_node_days": 3})
                database.connection.execute('DELETE FROM "系统统计" WHERE key = ?', ("stale_unvalidated_default_v1",))
                database.connection.commit()

            with NodeDatabase(path) as database:
                self.assertEqual(database.maintenance_config()["stale_unvalidated_node_days"], 2)

    def test_migrates_quality_pool_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.update_auto_config({
                    "valid_low_watermark": 20,
                    "collect_insert_target": 200,
                    "validate_valid_target": 50,
                })
                database.update_subscription_converter_config({"export_limit": 100})
                database.update_bot_config({"subscription_export_limit": 100})
                database.connection.execute('DELETE FROM "系统统计" WHERE key = ?', ("quality_pool_defaults_v1",))
                database.connection.commit()

            with NodeDatabase(path) as database:
                auto = database.auto_config()
                converter = database.subscription_converter_config()
                bot = database.bot_config()
                self.assertEqual(auto["valid_low_watermark"], 1000)
                self.assertEqual(auto["collect_insert_target"], 20000)
                self.assertEqual(auto["validate_valid_target"], 200)
                self.assertEqual(converter["export_limit"], 80)
                self.assertEqual(bot["subscription_export_limit"], 80)
