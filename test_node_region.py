import base64
import json
import unittest

from node_region import publish_region, region_from_country, region_from_text


class NodeRegionTest(unittest.TestCase):
    def test_country_codes_classify_publishable_regions(self):
        self.assertEqual(region_from_country("JP"), "primary_asia")
        self.assertEqual(region_from_country("US"), "us")
        self.assertEqual(region_from_country("MY"), "filler_asia")
        self.assertEqual(region_from_country("IN"), "excluded")
        self.assertEqual(region_from_country("ID"), "excluded")
        self.assertEqual(region_from_country("GB"), "excluded")
        self.assertEqual(region_from_country("ZA"), "excluded")
        self.assertEqual(region_from_country(""), "unknown")

    def test_uri_keywords_classify_region_without_country_field(self):
        self.assertEqual(region_from_text("vless://node@example.com:443#Tokyo"), "primary_asia")
        self.assertEqual(region_from_text("trojan://node@example.com:443#Los%20Angeles"), "us")
        self.assertEqual(region_from_text("vless://node@example.com:443#Vietnam"), "filler_asia")
        self.assertEqual(region_from_text("ss://node@example.com:443#London"), "excluded")
        self.assertEqual(region_from_text("vless://node@example.com:443#Russia"), "excluded")
        self.assertEqual(region_from_text("vless://node@example.com:443#unknown"), "excluded")
        self.assertEqual(region_from_text("vless://node@example.com:443#Telegram%20Channel"), "excluded")

    def test_vmess_remark_is_used_for_region_detection(self):
        payload = base64.urlsafe_b64encode(
            json.dumps({"ps": "Singapore fast", "add": "example.com", "port": "443", "id": "id"}).encode("utf-8")
        ).decode("ascii").rstrip("=")
        self.assertEqual(region_from_text("vmess://" + payload), "primary_asia")

    def test_publish_region_prefers_country_then_uri_text(self):
        self.assertEqual(publish_region({"country": "US", "uri": "vless://node@example.com:443#London"}), "us")
        self.assertEqual(publish_region({"country": "", "uri": "vless://node@example.com:443#Hong%20Kong"}), "primary_asia")


if __name__ == "__main__":
    unittest.main()
