import unittest
import tempfile
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


if __name__ == "__main__":
    unittest.main()
