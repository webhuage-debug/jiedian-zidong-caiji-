#!/usr/bin/env python3
"""Telegram bot polling service for keyword-triggered replies."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable

from node_database import NodeDatabase


def log(message: str) -> None:
    print(message, flush=True)


def keywords(value: object) -> set[str]:
    raw = str(value or "").replace(",", "\n")
    return {item.strip().lower() for item in raw.splitlines() if item.strip()}


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
                    "allowed_updates": json.dumps(["message"]),
                }, timeout=35).get("result", [])
                for update in updates:
                    self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                    self.handle_update(token, config, update)
            except (OSError, ValueError) as error:
                log("Telegram 请求失败，5 秒后重试 | " + self.describe_error(error))
                time.sleep(5)

    def handle_update(self, token: str, config: Dict[str, object], update: dict) -> None:
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "")
        user_id = str(sender.get("id") or "")
        username = str(sender.get("username") or sender.get("first_name") or "")
        if not text or not chat_id:
            return
        with NodeDatabase(self.database) as database:
            database.record_bot_message(user_id, chat_id, "收到", text)
        log("收到消息 | 用户 " + (username or user_id or "未知") + " | " + text)
        if text.lower() not in keywords(config["keywords"]):
            return
        reply = str(config["reply_message"]).strip() or "测试回复：BOT 已成功监测到关键字。"
        self.api(token, "sendMessage", {
            "chat_id": chat_id,
            "text": reply,
        })
        with NodeDatabase(self.database) as database:
            database.record_bot_message(user_id, chat_id, "发送", reply)
        log("关键字命中，已发送自动回复 | 用户 " + (username or user_id or "未知"))

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
