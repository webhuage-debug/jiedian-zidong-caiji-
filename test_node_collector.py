import base64
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from node_database import NodeDatabase
from node_collector import (
    Finding,
    DatabaseNodeSink,
    discover_blob_urls,
    extract_findings,
    is_safe_subscription_url,
    page_links,
    proxy_uri,
    resolve_subscriptions,
    safe_node_ref,
    should_download,
    should_follow_tree,
    should_parse_file_content,
)


class FakeClient:
    pages = {
        "https://github.com/owner/repo": (
            '<a href="/owner/repo/tree/main/sub">sub</a>'
            '<a href="/owner/repo/blob/main/root.txt">root</a>'
            '<a href="/other/repo/blob/main/ignored.txt">other repo</a>'
        ),
        "https://github.com/owner/repo/tree/main/sub": (
            '<a href="/owner/repo/blob/main/sub/nodes.yaml">nodes</a>'
        ),
    }

    def get_text(self, url, category=None):
        return self.pages[url]


class FakeSubscriptionClient:
    pages = {
        "https://sub.example.com/first": "dmxlc3M6Ly91dWlkQGV4YW1wbGUuY29tOjQ0MyNkZW1vCg==",
    }

    def get_text(self, url, category=None):
        return self.pages[url]


class ExtractFindingsTest(unittest.TestCase):
    def test_extracts_nodes_links_and_nested_base64(self):
        encoded = base64.b64encode(
            b"vless://uuid@example.com:443?security=tls#demo\n"
            b"trojan://secret@example.net:443#two\n"
        ).decode()
        text = (
            "subscription: https://example.com/api/v1/client/subscribe?token=abc\n"
            "plain: vmess://eyJhZGQiOiJleGFtcGxlLmNvbSJ9\n"
            + encoded
        )
        findings = extract_findings(text, "owner/repo", "nodes.txt")
        values = {item.value for item in findings}
        self.assertIn("vless://uuid@example.com:443?security=tls#demo", values)
        self.assertIn("trojan://secret@example.net:443#two", values)
        self.assertIn("vmess://eyJhZGQiOiJleGFtcGxlLmNvbSJ9", values)
        kinds = {item.value: item.kind for item in findings}
        self.assertEqual(kinds["https://example.com/api/v1/client/subscribe?token=abc"], "subscription_link")

    def test_yaml_inline_node_is_detected(self):
        findings = extract_findings(
            "proxies:\n  - url: ss://YWVzLTEyOC1nY206cGFzc0@example.org:8388#name\n",
            "owner/repo",
            "clash.yaml",
        )
        self.assertEqual(findings[0].kind, "node")

    def test_candidate_file_filter(self):
        self.assertTrue(should_download("subscriptions/all.txt", 100, 1000))
        self.assertTrue(should_download("nodes", None, 1000))
        self.assertFalse(should_download("image.png", 100, 1000))
        self.assertFalse(should_download("public/assets/app.js", 100, 1000))
        self.assertFalse(should_download("src/settings/index.json", 100, 1000))
        self.assertTrue(should_download("src/subscriptions/nodes.txt", 100, 1000))
        self.assertFalse(should_download("all.txt", 1001, 1000))

    def test_low_value_tree_filter_counts_skipped_directories(self):
        class Logger:
            def __init__(self):
                self.fields = []

            def emit(self, message, verbosity=0, **fields):
                self.fields.append(fields)

        logger = Logger()
        self.assertFalse(should_follow_tree("owner/repo", "https://github.com/owner/repo/tree/main/public/assets", 3, logger))
        self.assertTrue(should_follow_tree("owner/repo", "https://github.com/owner/repo/tree/main/src/subscriptions", 3, logger))
        self.assertEqual(logger.fields[0]["skipped_dirs_delta"], 1)

    def test_readme_content_is_only_parsed_when_it_contains_node_links(self):
        self.assertFalse(should_parse_file_content("README.md", "project docs only"))
        self.assertTrue(should_parse_file_content("README.md", "demo vless://uuid@example.com:443#HK"))

    def test_html_links_are_resolved_without_api(self):
        links = page_links('<a href="/owner/repo/tree/main/sub">sub</a>', "https://github.com/owner/repo")
        self.assertEqual(links, ["https://github.com/owner/repo/tree/main/sub"])

    def test_discovers_files_by_crawling_repository_html(self):
        blobs = discover_blob_urls(FakeClient(), "owner/repo", max_pages=10)
        self.assertEqual(
            [item.source for item in blobs if item.kind == "file"],
            [
                "root.txt",
                "sub/nodes.yaml",
            ],
        )

    def test_resolves_subscription_body_into_nodes(self):
        findings = [
            Finding("subscription_link", "https://sub.example.com/first", "owner/repo", "README.md", "plain", 2)
        ]
        resolved = resolve_subscriptions(FakeSubscriptionClient(), findings, 10, 2, 1000)
        self.assertIn("vless://uuid@example.com:443#demo", {item.value for item in resolved})

    def test_rejects_local_subscription_urls(self):
        self.assertFalse(is_safe_subscription_url("http://127.0.0.1/sub"))
        self.assertFalse(is_safe_subscription_url("http://localhost/sub"))
        self.assertTrue(is_safe_subscription_url("https://example.com/sub"))

    def test_stores_unique_nodes_without_text_export(self):
        with tempfile.TemporaryDirectory() as directory:
            exporter = DatabaseNodeSink(Path(directory) / "nodes.db")
            node = Finding("node", "vless://uuid@example.com:443#Tokyo", "owner/repo", "nodes.txt", "plain")
            exporter.consume([node, node])
            exporter.close()
            self.assertFalse((Path(directory) / "nodes.txt").exists())
            with NodeDatabase(Path(directory) / "nodes.db") as database:
                self.assertEqual(database.count("节点库"), 1)
                self.assertEqual(database.stats()["duplicate_filtered"], 1)

    def test_collection_sink_keeps_unknown_but_filters_ad_nodes_before_database(self):
        with tempfile.TemporaryDirectory() as directory:
            exporter = DatabaseNodeSink(Path(directory) / "nodes.db")
            exporter.consume([
                Finding("node", "vless://hk@example.com:443#Hong%20Kong", "owner/repo", "nodes.txt", "plain"),
                Finding("node", "vless://unknown@example.com:443#unknown", "owner/repo", "nodes.txt", "plain"),
                Finding("node", "vless://ad@example.com:443#Telegram%20Channel", "owner/repo", "nodes.txt", "plain"),
            ])
            exporter.close()
            with NodeDatabase(Path(directory) / "nodes.db") as database:
                self.assertEqual(database.count("节点库"), 2)
                rows = list(database.iter_nodes(revalidate=True))
                self.assertEqual(set(rows), {
                    "vless://hk@example.com:443#Hong%20Kong",
                    "vless://unknown@example.com:443#unknown",
                })

    def test_safe_node_ref_does_not_expose_full_link(self):
        value = safe_node_ref("vless://uuid@example.com:443?security=tls#Hong%20Kong")
        self.assertIn("vless://***@example.com:443#hash_", value)
        self.assertNotIn("uuid", value)

    def test_converts_structured_mihomo_yaml_node(self):
        findings = extract_findings(
            "proxies:\n  - name: demo\n    type: vless\n    server: example.com\n"
            "    port: 443\n    uuid: test-uuid\n    tls: true\n    servername: sni.example.com\n",
            "owner/repo",
            "clash.yaml",
        )
        self.assertIn(
            "vless://test-uuid@example.com:443?sni=sni.example.com&security=tls#demo",
            {item.value for item in findings},
        )

    def test_converts_mihomo_reality_node_without_losing_keys(self):
        uri = proxy_uri({
            "name": "reality",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "test-uuid",
            "tls": True,
            "servername": "www.microsoft.com",
            "client-fingerprint": "chrome",
            "reality-opts": {"public-key": "pub-key", "short-id": "abcd"},
        })

        parsed = urllib.parse.urlsplit(uri)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["security"], ["reality"])
        self.assertEqual(query["sni"], ["www.microsoft.com"])
        self.assertEqual(query["fp"], ["chrome"])
        self.assertEqual(query["pbk"], ["pub-key"])
        self.assertEqual(query["sid"], ["abcd"])

    def test_converts_mihomo_ws_grpc_and_xhttp_transport_options(self):
        ws = proxy_uri({
            "name": "ws",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "ws-uuid",
            "tls": True,
            "network": "ws",
            "ws-opts": {"path": "/ray", "headers": {"Host": "cdn.example.com"}},
        })
        ws_query = urllib.parse.parse_qs(urllib.parse.urlsplit(ws).query)
        self.assertEqual(ws_query["type"], ["ws"])
        self.assertEqual(ws_query["path"], ["/ray"])
        self.assertEqual(ws_query["host"], ["cdn.example.com"])

        grpc = proxy_uri({
            "name": "grpc",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "grpc-uuid",
            "network": "grpc",
            "grpc-opts": {"grpc-service-name": "svc"},
        })
        grpc_query = urllib.parse.parse_qs(urllib.parse.urlsplit(grpc).query)
        self.assertEqual(grpc_query["type"], ["grpc"])
        self.assertEqual(grpc_query["serviceName"], ["svc"])

        xhttp = proxy_uri({
            "name": "xhttp",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "xhttp-uuid",
            "network": "xhttp",
            "xhttp-opts": {"path": "/x", "host": "x.example.com", "mode": "auto"},
        })
        xhttp_query = urllib.parse.parse_qs(urllib.parse.urlsplit(xhttp).query)
        self.assertEqual(xhttp_query["type"], ["xhttp"])
        self.assertEqual(xhttp_query["path"], ["/x"])
        self.assertEqual(xhttp_query["host"], ["x.example.com"])
        self.assertEqual(xhttp_query["mode"], ["auto"])

    def test_converts_shadowsocks_dict(self):
        self.assertEqual(
            proxy_uri({"type": "ss", "server": "example.com", "port": 8388, "cipher": "aes-128-gcm", "password": "pw"}),
            "ss://YWVzLTEyOC1nY206cHc@example.com:8388",
        )


if __name__ == "__main__":
    unittest.main()
