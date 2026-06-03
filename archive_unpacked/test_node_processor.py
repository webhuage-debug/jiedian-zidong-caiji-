import base64
import json
import unittest

from node_processor import processed_nodes, subscription_base64


class NodeProcessorTest(unittest.TestCase):
    def test_renames_vless_fragment_without_touching_original(self):
        node = {
            "uri": "vless://uuid@example.com:443?security=tls#old",
            "protocol": "vless",
            "country": "US",
            "proxy_ips": "203.0.113.1",
            "seconds": 1.2,
            "last_validated": "2026-06-02 08:00:00",
        }
        row = processed_nodes([node], "{country_name} {protocol} {validated_date} #{index}")[0]
        self.assertEqual(row["name"], "美国 VLESS 2026-06-02 #001")
        self.assertIn("#%E7%BE%8E%E5%9B%BD%20VLESS%202026-06-02%20%23001", row["uri"])
        self.assertEqual(row["original_uri"], node["uri"])

    def test_renames_vmess_payload_and_exports_base64_subscription(self):
        payload = base64.b64encode(json.dumps({
            "v": "2",
            "ps": "old",
            "add": "example.com",
            "port": "443",
            "id": "uuid",
            "aid": "0",
            "net": "tcp",
            "type": "none",
            "host": "",
            "path": "/",
            "tls": "tls",
        }).encode()).decode().rstrip("=")
        node = {
            "uri": "vmess://" + payload,
            "protocol": "vmess",
            "country": "DE",
            "proxy_ips": "203.0.113.2",
            "seconds": 2.5,
            "last_validated": "2026-06-02 08:00:00",
        }
        result = subscription_base64([node], "{country_name} {protocol} {index}")
        plain = base64.b64decode(result["subscription"]).decode()
        self.assertTrue(plain.startswith("vmess://"))
        vmess_payload = plain.split("://", 1)[1]
        decoded = json.loads(base64.urlsafe_b64decode(vmess_payload + "=" * (-len(vmess_payload) % 4)))
        self.assertEqual(decoded["ps"], "德国 VMESS 001")
        self.assertEqual(decoded["name"], "德国 VMESS 001")
        self.assertEqual(result["count"], 1)


if __name__ == "__main__":
    unittest.main()
