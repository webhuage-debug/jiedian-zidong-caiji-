import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from services.acceptance_service import acceptance_reports, build_acceptance_command, cleanup_acceptance_reports
from services.converter_service import (
    SUB_STORE_PROJECT_URL,
    sub_store_download_url,
    subscription_conversion_cache_identity,
    subscription_converter_targets,
)
from services.xray_service import parse_releases, release_asset_matches


class ServiceExtractionTest(unittest.TestCase):
    def test_acceptance_command_and_report_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "data" / "reports"
            reports.mkdir(parents=True)
            for index in range(12):
                payload = {
                    "started_at": "2026-06-05 00:00:00",
                    "finished_at": "2026-06-05 00:00:01",
                    "mode": "smoke",
                    "claim_summary": {"total": 1, "success": 1, "failed": 0},
                    "final_database": {"valid_nodes": index},
                }
                path = reports / ("acceptance-20260605-0000" + str(index).zfill(2) + ".json")
                path.write_text(json.dumps(payload), encoding="utf-8")
                path.with_suffix(".md").write_text("ok", encoding="utf-8")
                old = time.time() - (index + 1) * 86400
                os.utime(path, (old, old))
                os.utime(path.with_suffix(".md"), (old, old))

            command = build_acceptance_command({"smoke": True, "claim_rounds": 2}, "adminhuage")
            self.assertIn("e2e_acceptance_runner.py", command)
            self.assertIn("--smoke", command)
            self.assertEqual(acceptance_reports(root, 2)[0]["summary"]["success"], 1)

            result = cleanup_acceptance_reports(root, {
                "acceptance_report_days": 99,
                "acceptance_failed_report_days": 99,
                "acceptance_report_max_files": 10,
            })
            self.assertEqual(result["acceptance_reports_deleted"], 4)

    def test_converter_service_identity_and_url(self):
        config = {
            "backend_url": "http://127.0.0.1:3001",
            "profile_name": "sub",
            "export_limit": 20,
            "prefer_asia": True,
        }
        targets = subscription_converter_targets()
        self.assertTrue(any(item["id"] == "v2rayng" for item in targets))
        self.assertEqual(SUB_STORE_PROJECT_URL, "https://github.com/sub-store-org/Sub-Store")
        url = sub_store_download_url(config, "v2rayng", "vless://example")
        self.assertIn("target=V2Ray", url)
        self.assertNotIn("content=", url)
        identity = subscription_conversion_cache_identity(config, "v2rayng", "vless://example", "custom", "vless", "v1")
        self.assertEqual(len(identity["cache_key"]), 64)

    def test_xray_release_parser_marks_matching_assets(self):
        payload = [{
            "tag_name": "v1.2.3",
            "name": "v1.2.3",
            "published_at": "2026-06-01T00:00:00Z",
            "assets": [
                {
                    "name": "Xray-windows-64.zip",
                    "browser_download_url": "https://github.com/XTLS/Xray-core/releases/download/v1.2.3/Xray-windows-64.zip",
                    "size": 10,
                },
                {
                    "name": "Xray-linux-arm64-v8a.zip",
                    "browser_download_url": "https://github.com/XTLS/Xray-core/releases/download/v1.2.3/Xray-linux-arm64-v8a.zip",
                    "size": 20,
                },
            ],
        }]
        releases = parse_releases(payload, "windows", "amd64")
        self.assertEqual(releases[0]["version"], "v1.2.3")
        self.assertTrue(releases[0]["assets"][0]["matched"])
        self.assertFalse(releases[0]["assets"][1]["matched"])
        self.assertTrue(release_asset_matches("Xray-linux-arm64-v8a.zip", "linux", "arm64"))


if __name__ == "__main__":
    unittest.main()
