import tempfile
import unittest
import json
from pathlib import Path

from bot_service import TelegramBot, bot_private_start_url, keywords
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

    def test_group_keyword_sends_group_prompt_and_records_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_bot_config({
                    "keywords": "节点\n订阅",
                    "group_prompt_message": "请私聊领取",
                })
            bot = FakeTelegramBot(path)
            bot.handle_update("token", config, {
                "message": {
                    "text": "节点",
                    "chat": {"id": 100, "type": "group"},
                    "from": {"id": 200, "username": "tester"},
                }
            })
            self.assertEqual(bot.calls, [("token", "sendMessage", {"chat_id": "100", "text": "请私聊领取"})])
            with NodeDatabase(path) as database:
                messages = database.bot_message_logs()
            self.assertEqual([item["direction"] for item in messages], ["发送", "收到"])

    def test_group_keyword_adds_private_claim_button_when_bot_username_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_bot_config({
                    "bot_username": "@HuageNodeBot",
                    "keywords": "我要节点",
                    "group_prompt_message": "点击按钮私聊领取",
                })
            bot = FakeTelegramBot(path)
            result = bot.handle_message("token", config, "我要节点", "-100001", "group", "200001", "tester")
            self.assertEqual(result["action"], "group_prompt")
            self.assertEqual(bot.calls[0][2]["chat_id"], "-100001")
            self.assertIn("reply_markup", bot.calls[0][2])
            self.assertIn("https://t.me/HuageNodeBot?start=claim", bot.calls[0][2]["reply_markup"])
            self.assertEqual(result["replies"][0]["reply_markup"]["inline_keyboard"][0][0]["url"], "https://t.me/HuageNodeBot?start=claim")

    def test_private_start_claim_sends_instruction_without_repeating_keyword(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.update_claim_code_config({"version": "v8"})
                config = database.update_bot_config({
                    "keywords": "我要节点",
                    "private_instruction_message": "当前版本 {version}",
                })
            bot = FakeTelegramBot(path)
            result = bot.handle_message("token", config, "/start claim", "200001", "private", "200001", "tester")
            self.assertEqual(result["action"], "private_instruction")
            self.assertEqual(bot.calls[0][2]["text"], "当前版本 v8")
            self.assertFalse(result["matched_keyword"])

    def test_bot_private_start_url_uses_deep_link_payload(self):
        self.assertEqual(
            bot_private_start_url({"bot_username": "@HuageNodeBot"}, "claim"),
            "https://t.me/HuageNodeBot?start=claim",
        )

    def test_non_matching_keyword_does_not_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.bot_config()
            bot = FakeTelegramBot(path)
            bot.handle_update("token", config, {
                "message": {"text": "其他", "chat": {"id": 100, "type": "group"}, "from": {"id": 200}}
            })
            self.assertEqual(bot.calls, [])

    def test_private_keyword_sends_claim_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.update_claim_code_config({"version": "v9"})
                config = database.update_bot_config({
                    "keywords": "节点",
                    "private_instruction_message": "{youtube_guide_message}\n版本 {version} 地址 {public_base_url}",
                    "youtube_guide_message": "订阅 {youtube_channel_url} 看 {latest_free_node_video_url}",
                    "youtube_channel_url": "https://youtube.com/@huage",
                    "latest_free_node_video_url": "https://youtube.com/watch?v=free",
                    "public_base_url": "https://node.example.com",
                })
            bot = FakeTelegramBot(path)
            bot.handle_update("token", config, {
                "message": {"text": "节点", "chat": {"id": 200, "type": "private"}, "from": {"id": 200}}
            })
            self.assertEqual(
                bot.calls[0][2]["text"],
                "订阅 https://youtube.com/@huage 看 https://youtube.com/watch?v=free\n版本 v9 地址 https://node.example.com",
            )

    def test_private_claim_code_sends_subscription_card(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                database.update_claim_code_config({
                    "code": "HUAGE2026",
                    "version": "v2",
                    "daily_limit": 1,
                    "success_message": "ok",
                    "wrong_code_message": "wrong",
                    "expired_message": "expired",
                    "limit_exceeded_message": "limited",
                })
                config = database.update_bot_config({
                    "public_base_url": "https://node.example.com",
                    "subscription_card_message": "V2RayNG: {subscription_url}\nSurge: {surge_url}\nShadowrocket: {shadowrocket_url}",
                    "subscription_max_uses": 3,
                    "subscription_expire_hours": 2,
                    "subscription_export_limit": 50,
                })
            bot = FakeTelegramBot(path)
            bot.handle_update("token", config, {
                "message": {
                    "text": "HUAGE2026",
                    "chat": {"id": 200, "type": "private"},
                    "from": {"id": 200, "username": "tester"},
                }
            })
            self.assertEqual(len(bot.calls), 1)
            sent_text = bot.calls[0][2]["text"]
            self.assertIn("ok", sent_text)
            self.assertIn("V2RayNG: https://node.example.com/sub/", sent_text)
            self.assertIn("Surge: https://node.example.com/sub/", sent_text)
            self.assertIn("target=surge", sent_text)
            self.assertIn("Shadowrocket: https://node.example.com/sub/", sent_text)
            self.assertIn("target=shadowrocket", sent_text)
            reply_markup = json.loads(bot.calls[0][2]["reply_markup"])
            flattened = [button for row in reply_markup["inline_keyboard"] for button in row]
            urls = {button["text"]: button["url"] for button in flattened}
            self.assertIn("target=clash-verge", urls["Clash Verge"])
            self.assertIn("target=sing-box", urls["Sing-box"])
            self.assertIn("target=raw", urls["原始节点"])
            with NodeDatabase(path) as database:
                links = database.subscription_links()
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0]["max_uses"], 3)
                self.assertEqual(links[0]["export_limit"], 50)

    def test_simulated_group_keyword_does_not_call_telegram_api(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nodes.db"
            with NodeDatabase(path) as database:
                config = database.update_bot_config({
                    "keywords": "节点",
                    "group_prompt_message": "请私聊领取",
                })
            bot = FakeTelegramBot(path)
            result = bot.handle_message("token", config, "节点", "-100001", "group", "200001", "tester", simulate=True)
            self.assertEqual(bot.calls, [])
            self.assertTrue(result["matched_keyword"])
            self.assertEqual(result["action"], "group_prompt")
            self.assertEqual(result["replies"][0]["text"], "请私聊领取")
            with NodeDatabase(path) as database:
                messages = database.bot_message_logs()
            self.assertEqual([item["direction"] for item in messages], ["模拟发送", "收到"])


if __name__ == "__main__":
    unittest.main()
