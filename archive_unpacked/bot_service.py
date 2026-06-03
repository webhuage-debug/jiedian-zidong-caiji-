#!/usr/bin/env python3
"""Telegram bot polling service for YouTube claim-code subscription delivery."""

from __future__ import annotations

import argparse
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional

from app_time import beijing_now
from node_database import NodeDatabase


VERIFY_CODE_CALLBACK = "claim:verify"
YOUTUBE_CALLBACK = "claim:youtube"
WAITING_FOR_CODE = "waiting_for_claim_code"


def log(message: str) -> None:
    print(message, flush=True)


def keywords(value: object) -> set[str]:
    raw = str(value or "").replace(",", "\n")
    return {item.strip().lower() for item in raw.splitlines() if item.strip()}


def username_of(sender: dict) -> str:
    username = str(sender.get("username") or "").strip()
    if username:
        return "@" + username
    return str(sender.get("first_name") or sender.get("last_name") or "").strip()


def chat_type(chat: dict) -> str:
    return str(chat.get("type") or "private")


def is_group_chat(chat: dict) -> bool:
    return chat_type(chat) in ("group", "supergroup")


def parse_beijing_time(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def normalized_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    return "https://" + text


class TelegramBot:
    def __init__(self, database: Path):
        self.database = database
        self.offset = 0
        self.last_wait_log = 0.0

    def run(self) -> None:
        log("BOT 机器人进程已启动")
        while True:
            with NodeDatabase(self.database) as database:
                config = database.bot_config()
            token = str(config["bot_token"])
            if not token:
                if time.time() - self.last_wait_log > 30:
                    log("等待配置：请在后台填写 Telegram Bot Token 后保存")
                    self.last_wait_log = time.time()
                time.sleep(3)
                continue
            try:
                updates = self.api(token, "getUpdates", {
                    "offset": self.offset,
                    "timeout": 25,
                    "allowed_updates": json.dumps(["message", "callback_query"]),
                }, timeout=35).get("result", [])
                for update in updates:
                    self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                    self.handle_update(token, config, update)
            except (OSError, ValueError) as error:
                log("Telegram 请求失败，5 秒后重试 | " + self.describe_error(error))
                time.sleep(5)

    def handle_update(self, token: str, config: Dict[str, object], update: dict) -> None:
        if update.get("callback_query"):
            return self.handle_callback(token, update["callback_query"])
        if update.get("message"):
            return self.handle_message(token, config, update["message"])

    def handle_message(self, token: str, config: Dict[str, object], message: dict) -> None:
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "")
        user_id = str(sender.get("id") or "")
        username = username_of(sender)
        if not text or not chat_id or not user_id:
            return
        with NodeDatabase(self.database) as database:
            database.record_bot_message(user_id, chat_id, "收到", text)
            state = database.bot_claim_state(user_id)
        log("收到消息 | 用户 " + (username or user_id) + " | " + text)

        if chat_type(chat) == "private" and state.get("state") == WAITING_FOR_CODE:
            return self.verify_claim_code(token, user_id, username, chat_id, text)

        if text.lower() not in keywords(config["keywords"]):
            return

        if is_group_chat(chat):
            return self.start_group_claim_flow(token, chat_id, user_id, username)
        return self.send_claim_card(token, chat_id, user_id, username)

    def start_group_claim_flow(self, token: str, group_chat_id: str, user_id: str, username: str) -> None:
        with NodeDatabase(self.database) as database:
            claim_config = database.claim_config()
        try:
            self.send_claim_card(token, user_id, user_id, username)
            group_text = str(claim_config["group_dm_success_message"])
            self.send_message(token, group_chat_id, group_text)
            self.record_sent(user_id, group_chat_id, group_text)
            log("群组触发成功，已私发领取卡片 | 用户 " + (username or user_id))
        except (OSError, ValueError) as error:
            group_text = str(claim_config["group_dm_failed_message"])
            self.send_message(token, group_chat_id, group_text)
            self.record_sent(user_id, group_chat_id, group_text)
            log("无法私发用户 | 用户 " + (username or user_id) + " | " + self.describe_error(error))

    def send_claim_card(self, token: str, chat_id: str, user_id: str, username: str) -> None:
        with NodeDatabase(self.database) as database:
            claim_config = database.claim_config()
            database.set_bot_claim_state(user_id, chat_id, username, "")
        text = str(claim_config["claim_prompt_message"])
        channel = normalized_url(claim_config.get("youtube_channel_url"))
        youtube_button = {"text": "去 YouTube 订阅", "callback_data": YOUTUBE_CALLBACK}
        if channel:
            youtube_button = {"text": "去 YouTube 订阅", "url": channel}
        keyboard = {
            "inline_keyboard": [
                [youtube_button],
                [{"text": "我已订阅，验证口令", "callback_data": VERIFY_CODE_CALLBACK}],
            ]
        }
        self.send_message(token, chat_id, text, reply_markup=keyboard)
        self.record_sent(user_id, chat_id, text)

    def handle_callback(self, token: str, callback: dict) -> None:
        data = str(callback.get("data") or "")
        sender = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or sender.get("id") or "")
        user_id = str(sender.get("id") or "")
        username = username_of(sender)
        callback_id = str(callback.get("id") or "")
        if callback_id:
            self.api(token, "answerCallbackQuery", {"callback_query_id": callback_id}, timeout=10)
        if not user_id or not chat_id:
            return
        with NodeDatabase(self.database) as database:
            claim_config = database.claim_config()
        if data == YOUTUBE_CALLBACK:
            text = str(claim_config["youtube_button_message"]).strip()
            channel = normalized_url(claim_config["youtube_channel_url"])
            if channel:
                text += "\n\n频道链接：" + channel
            self.send_message(token, chat_id, text)
            self.record_sent(user_id, chat_id, text)
            return
        if data == VERIFY_CODE_CALLBACK:
            with NodeDatabase(self.database) as database:
                database.set_bot_claim_state(user_id, chat_id, username, WAITING_FOR_CODE)
            text = str(claim_config["ask_code_message"])
            self.send_message(token, chat_id, text)
            self.record_sent(user_id, chat_id, text)

    def verify_claim_code(self, token: str, user_id: str, username: str, chat_id: str, text: str) -> None:
        with NodeDatabase(self.database) as database:
            claim_config = database.claim_config()
        expected = str(claim_config["claim_code"]).strip()
        version = str(claim_config["claim_version"]).strip()
        expires_at = parse_beijing_time(claim_config.get("claim_expires_at"))
        if not expected or text.strip() != expected:
            return self.send_configured_reply(token, user_id, chat_id, "wrong_code_message")
        if expires_at and beijing_now().replace(tzinfo=None) >= expires_at:
            return self.send_configured_reply(token, user_id, chat_id, "expired_code_message")
        with NodeDatabase(self.database) as database:
            daily_count = database.bot_claim_count_today(user_id, version)
            daily_limit = int(claim_config["daily_claim_limit"] or 1)
            if daily_count >= daily_limit:
                return self.send_configured_reply(token, user_id, chat_id, "limit_message")
            link = self.create_user_subscription(database, user_id, username, version, claim_config)
            database.record_bot_claim(user_id, username, version, str(link["token"]))
            database.clear_bot_claim_state(user_id)
        public_base_url = str(claim_config.get("public_base_url") or "").strip()
        if not public_base_url:
            with NodeDatabase(self.database) as database:
                bot_config = database.bot_config()
            public_base_url = str(bot_config.get("public_base_url") or "http://127.0.0.1:8766").strip()
        subscription_url = public_base_url.rstrip("/") + "/sub/" + str(link["token"])
        reply = str(claim_config["success_message"]).strip() + "\n\n请选择你的代理软件格式："
        keyboard = {
            "inline_keyboard": [
                [{"text": "V2RayN / V2RayNG", "url": subscription_url}],
                [{"text": "Clash Verge", "url": subscription_url + "?target=clash"}],
                [{"text": "Sing-box", "url": subscription_url + "?target=singbox"}],
                [{"text": "Surge", "url": subscription_url + "?target=surge"}],
                [{"text": "Shadowrocket 小火箭", "url": subscription_url + "?target=shadowrocket"}],
            ]
        }
        self.send_message(token, chat_id, reply, reply_markup=keyboard)
        self.record_sent(user_id, chat_id, reply)
        log("领取口令验证成功，已发送订阅链接 | 用户 " + (username or user_id) + " | 版本 " + version)

    def create_user_subscription(self, database: NodeDatabase, user_id: str, username: str, version: str, claim_config: dict) -> dict:
        expires_at = str(claim_config.get("claim_expires_at") or "").strip() or None
        if not expires_at:
            expires_at = (beijing_now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        name = "BOT领取 " + (username or user_id)
        remark = "Telegram 用户 " + user_id + " | 口令版本 " + version
        return database.create_subscription_link(
            secrets.token_hex(16),
            name,
            "either",
            10,
            expires_at,
            "",
            remark,
            claim_version=version,
            created_by="bot",
            telegram_user_id=user_id,
            telegram_username=username,
        )

    def send_configured_reply(self, token: str, user_id: str, chat_id: str, key: str) -> None:
        with NodeDatabase(self.database) as database:
            claim_config = database.claim_config()
        text = str(claim_config[key])
        self.send_message(token, chat_id, text)
        self.record_sent(user_id, chat_id, text)

    def send_message(self, token: str, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> dict:
        fields: Dict[str, object] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            fields["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        return self.api(token, "sendMessage", fields)

    def record_sent(self, user_id: str, chat_id: str, text: str) -> None:
        with NodeDatabase(self.database) as database:
            database.record_bot_message(user_id, chat_id, "发送", text)

    def api(self, token: str, method: str, fields: Dict[str, object], timeout: int = 20) -> dict:
        url = "https://api.telegram.org/bot" + token + "/" + method
        body = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise ValueError(str(payload.get("description") or "Telegram 接口返回失败"))
        return payload

    @staticmethod
    def describe_error(error: Exception) -> str:
        if isinstance(error, urllib.error.HTTPError):
            if error.code == 401:
                return "Bot Token 无效"
            if error.code == 409:
                return "同一个 Bot Token 已有其他 getUpdates 实例在运行，请先停止 VPS 或其他旧版 BOT"
            if error.code == 403:
                return "用户尚未私聊机器人或机器人无权发送消息"
            return "HTTP 状态码 " + str(error.code)
        if isinstance(error, urllib.error.URLError):
            return "无法连接 Telegram：" + str(error.reason)
        return str(error)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    TelegramBot(args.database).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
