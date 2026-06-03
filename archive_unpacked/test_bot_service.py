import tempfile
import unittest
from pathlib import Path

from bot_service import TelegramBot, keywords
from node_database import NodeDatabase


class FakeTelegramBot(TelegramBot):
    def __init__(self, database: Path):
        super().__init__(database)
        self.calls = []

    def api(self, token, method, fields, timeout=20):
        self.calls.append((token, method, fields))
        return {"ok": True, "result": []}


class TelegramBotTest(unittest.TestCase):
    def test_keywords_accept_lines_and_commas(self):
        self.assertEqual(keywords("节点\n订阅,VMTOK"), {"节点", "订阅", "vmtok"})

    def test_matching_keyword_sends_configured_reply_and_records_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_bot_config({
                    "keywords": "节点\n订阅",
                    "reply_message": "测试回复成功",
                })
            bot = FakeTelegramBot(path)
            bot.handle_update("token", config, {
                "message": {
                    "text": "节点",
                    "chat": {"id": 100},
                    "from": {"id": 200, "username": "tester"},
                }
            })
            self.assertEqual(bot.calls, [("token", "sendMessage", {"chat_id": "100", "text": "测试回复成功"})])
            with NodeDatabase(path) as database:
                messages = database.bot_message_logs()
            self.assertEqual([item["direction"] for item in messages], ["发送", "收到"])

    def test_non_matching_keyword_does_not_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.bot_config()
            bot = FakeTelegramBot(path)
            bot.handle_update("token", config, {
                "message": {"text": "其他", "chat": {"id": 100}, "from": {"id": 200}}
            })
            self.assertEqual(bot.calls, [])


if __name__ == "__main__":
    unittest.main()
