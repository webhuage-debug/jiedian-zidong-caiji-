import os
import tempfile
import unittest
from pathlib import Path

from e2e_acceptance_runner import record_acceptance_daily_stats, validate_until
from node_database import NodeDatabase


class AcceptanceRunnerStatsTest(unittest.TestCase):
    def test_records_acceptance_daily_stats_without_report_details(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                report = {
                    "finished_at": "2026-06-05 12:00:00",
                    "claim_summary": {
                        "total": 3,
                        "success": 2,
                        "failed": 1,
                        "by_target": {
                            "v2rayng": {"total": 2, "success": 2, "failed": 0},
                            "surge": {"total": 1, "success": 0, "failed": 1},
                        },
                    },
                    "claims": [
                        {"latency_ms": 100, "ok": True},
                        {"latency_ms": 200, "ok": True},
                        {"latency_ms": 350, "ok": False},
                    ],
                }
                record_acceptance_daily_stats(report)
                with NodeDatabase(Path("data") / "nodes.db") as database:
                    rows = {
                        (item["category"], item["name"]): item
                        for item in database.daily_ops_stats(20)
                    }
                self.assertEqual(rows[("acceptance", "total")]["count"], 3)
                self.assertEqual(rows[("acceptance", "total")]["total_value"], 650)
                self.assertEqual(rows[("acceptance", "total")]["max_value"], 350)
                self.assertEqual(rows[("acceptance", "success")]["count"], 2)
                self.assertEqual(rows[("acceptance_target", "surge:failed")]["count"], 1)
            finally:
                os.chdir(original_cwd)

    def test_validate_until_stops_after_repeated_no_yield_batches(self):
        class FakeClient:
            def __init__(self):
                self.starts = []
                self.stats_calls = 0

            def post(self, path, payload):
                if path == "/api/validator/start":
                    self.starts.append(payload)
                return {}

            def get(self, path):
                if path == "/api/status":
                    self.stats_calls += 1
                    database = {
                        "valid_nodes": 10,
                        "pending_nodes": max(1, 1000 - self.stats_calls * 100),
                        "total_nodes": max(1, 1000 - self.stats_calls * 100),
                    }
                    return {"tasks": {"validator": {"running": False}}, "database": database}
                if path == "/api/stats":
                    self.stats_calls += 1
                    return {
                        "valid_nodes": 10,
                        "pending_nodes": max(1, 1000 - self.stats_calls * 100),
                        "total_nodes": max(1, 1000 - self.stats_calls * 100),
                    }
                raise AssertionError(path)

        result = validate_until(FakeClient(), 1200, 0, 10)

        self.assertEqual(result["reason"], "no valid yield after 3 batches")
        self.assertEqual(result["batch_limit"], 300)
        self.assertEqual(result["no_yield_batches"], 3)


if __name__ == "__main__":
    unittest.main()
