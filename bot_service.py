#!/usr/bin/env python3
"""Telegram bot polling service for claim-code based subscription delivery."""

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
from typing import Dict, Iterable

from app_time import beijing_date, beijing_now
from node_database import NodeDatabase


def log(message: str) -> None:
    print(message, flush=True)


def keywords(value: object) -> set[str]:
    raw = str(value or "").replace(",", "\n")
    return {item.strip().lower() for item in raw.splitlines() if item.strip()}


def normalize_base_url(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    return text or "https://node.huage.us"


def youtube_channel_url(config: Dict[str, object]) -> str:
    return str(config.get("youtube_channel_url") or config.get("youtube_url") or "").strip()


def bot_private_start_url(config: Dict[str, object], payload: str = "claim") -> str:
    username = str(config.get("bot_username") or "").strip().lstrip("@")
    if not username:
        return ""
    return "https://t.me/" + username + "?start=" + urllib.parse.quote(payload)


def render_template(template: object, context: Dict[str, object]) -> str:
    text = str(template or "")
    for key, value in context.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def claim_code_expired(config: Dict[str, object]) -> bool:
    expires_at = str(config.get("expires_at") or "").strip()
    if not expires_at:
        return False
    try:
        return datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S") <= beijing_now().replace(tzinfo=None)
    except ValueError:
        return True


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

    def handle_update(self, token: str, config: Dict[str, object], update: dict) -> dict:
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "")
        chat_type = str(chat.get("type") or "private")
        user_id = str(sender.get("id") or "")
        username = str(sender.get("username") or sender.get("first_name") or "")
        return self.handle_message(token, config, text, chat_id, chat_type, user_id, username, simulate=False)

    def handle_message(
        self,
        token: str,
        config: Dict[str, object],
        text: str,
        chat_id: str,
        chat_type: str,
        user_id: str,
        username: str = "",
        simulate: bool = False,
    ) -> dict:
        text = str(text or "").strip()
        chat_id = str(chat_id or "").strip()
        chat_type = str(chat_type or "private").strip() or "private"
        user_id = str(user_id or "").strip()
        username = str(username or "").strip()
        result = {
            "received": bool(text and chat_id),
            "chat_type": chat_type,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "text": text,
            "matched_keyword": False,
            "action": "ignored",
            "status": "ignored",
            "reason": "",
            "replies": [],
            "subscription_created": False,
            "subscription": None,
            "simulate": simulate,
        }
        if not text or not chat_id:
            result["reason"] = "消息内容或会话 ID 为空"
            return result

        with NodeDatabase(self.database) as database:
            database.record_bot_message(user_id, chat_id, "收到", text)
        log("收到消息 | 用户 " + (username or user_id or "未知") + " | " + text)

        matched_keyword = text.lower() in keywords(config["keywords"])
        result["matched_keyword"] = matched_keyword
        if chat_type in ("group", "supergroup"):
            if matched_keyword:
                reply = self.send_group_claim_prompt(token, config, user_id, chat_id, simulate=simulate)
                result.update({"action": "group_prompt", "status": "sent", "reason": "群组关键词命中"})
                result["replies"].append(reply)
                log("群组关键词命中，已发送群内提示 | 用户 " + (username or user_id or "未知"))
            else:
                result["reason"] = "群组消息未命中关键词"
            return result

        lower_text = text.lower()
        if lower_text in ("/start", "start", "开始") or lower_text.startswith("/start ") or matched_keyword:
            reply = self.send_private_instruction(token, config, user_id, chat_id, simulate=simulate)
            result.update({"action": "private_instruction", "status": "sent", "reason": "私聊关键词或开始命令"})
            result["replies"].append(reply)
            return result

        claim_result = self.verify_private_claim(token, config, user_id, chat_id, username, text, simulate=simulate)
        result.update(claim_result)
        return result

    def send_group_claim_prompt(self, token: str, config: Dict[str, object], user_id: str, chat_id: str, simulate: bool = False) -> dict:
        private_url = bot_private_start_url(config, "claim")
        context = {
            "bot_private_url": private_url,
            "bot_username": str(config.get("bot_username") or "").strip(),
        }
        text = render_template(config.get("group_prompt_message"), context)
        reply_markup = None
        if private_url:
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "私聊领取节点", "url": private_url}
                ]]
            }
        return self.send_and_record(token, user_id, chat_id, text, simulate=simulate, reply_markup=reply_markup)

    def send_private_instruction(self, token: str, config: Dict[str, object], user_id: str, chat_id: str, simulate: bool = False) -> dict:
        with NodeDatabase(self.database) as database:
            claim_config = database.claim_code_config()
        context = {
            "version": claim_config.get("version", ""),
            "expires_at": claim_config.get("expires_at") or "未设置",
            "public_base_url": normalize_base_url(config.get("public_base_url")),
            "youtube_channel_url": youtube_channel_url(config),
            "latest_free_node_video_url": str(config.get("latest_free_node_video_url") or "").strip(),
            "youtube_guide_message": render_template(config.get("youtube_guide_message", ""), {
                "youtube_channel_url": youtube_channel_url(config),
                "latest_free_node_video_url": str(config.get("latest_free_node_video_url") or "").strip(),
            }),
        }
        return self.send_and_record(token, user_id, chat_id, render_template(config["private_instruction_message"], context), simulate=simulate)

    def verify_private_claim(
        self,
        token: str,
        config: Dict[str, object],
        user_id: str,
        chat_id: str,
        username: str,
        code: str,
        simulate: bool = False,
    ) -> dict:
        today = beijing_date()
        with NodeDatabase(self.database) as database:
            claim_config = database.claim_code_config()
            version = str(claim_config["version"])
            status = "success"
            message = str(claim_config["success_message"])
            client_key = user_id or chat_id
            if not claim_config["enabled"] or claim_code_expired(claim_config):
                status = "expired"
                message = str(claim_config["expired_message"])
            elif code != str(claim_config["code"]):
                status = "wrong_code"
                message = str(claim_config["wrong_code_message"])
            elif database.claim_success_count(today, client_key, version) >= int(claim_config["daily_limit"]):
                status = "limit_exceeded"
                message = str(claim_config["limit_exceeded_message"])
            database.record_claim_attempt(today, client_key, version, code, status, "", "telegram-bot")
            subscription = self.create_bot_subscription(database, config, user_id, username) if status == "success" else None

        if status != "success":
            reply = self.send_and_record(token, user_id, chat_id, message, simulate=simulate)
            log("私聊口令验证失败 | " + status + " | 用户 " + (username or user_id or "未知"))
            return {
                "action": "claim_code",
                "status": status,
                "reason": message,
                "replies": [reply],
                "subscription_created": False,
                "subscription": None,
            }

        reply = self.send_and_record(
            token,
            user_id,
            chat_id,
            message + "\n\n" + self.subscription_card(config, subscription or {}),
            simulate=simulate,
            reply_markup=self.subscription_reply_markup(config, subscription or {}),
        )
        log("私聊口令验证成功，已发送订阅卡片 | 用户 " + (username or user_id or "未知"))
        return {
            "action": "claim_code",
            "status": status,
            "reason": message,
            "replies": [reply],
            "subscription_created": True,
            "subscription": subscription,
        }

    def create_bot_subscription(self, database: NodeDatabase, config: Dict[str, object], user_id: str, username: str) -> dict:
        token = secrets.token_urlsafe(18)
        expires_at = (beijing_now() + timedelta(hours=int(config.get("subscription_expire_hours") or 24))).strftime("%Y-%m-%d %H:%M:%S")
        name = ("BOT " + (username or user_id or "user"))[:80]
        return database.create_subscription_link(
            token,
            name,
            "either",
            max_uses=int(config.get("subscription_max_uses") or 10),
            expires_at=expires_at,
            remark="telegram-bot:" + (user_id or ""),
            export_limit=int(config.get("subscription_export_limit") or 100),
        )

    def subscription_card(self, config: Dict[str, object], subscription: dict) -> str:
        subscription_url = normalize_base_url(config.get("public_base_url")) + "/sub/" + str(subscription.get("token") or "")
        urls = self.subscription_format_urls(config, subscription)
        context = {
            "subscription_url": subscription_url,
            "base64_url": urls["base64"],
            "v2rayng_url": urls["v2rayng"],
            "clash_verge_url": urls["clash-verge"],
            "sing_box_url": urls["sing-box"],
            "surge_url": urls["surge"],
            "shadowrocket_url": urls["shadowrocket"],
            "raw_url": urls["raw"],
            "expires_at": subscription.get("expires_at") or "未设置",
            "max_uses": subscription.get("max_uses") or "",
        }
        return render_template(config["subscription_card_message"], context)

    def subscription_format_urls(self, config: Dict[str, object], subscription: dict) -> Dict[str, str]:
        base_url = normalize_base_url(config.get("public_base_url")) + "/sub/" + str(subscription.get("token") or "")
        return {
            "base64": base_url,
            "raw": base_url + "?target=raw",
            "v2rayng": base_url + "?target=v2rayng",
            "clash-verge": base_url + "?target=clash-verge",
            "sing-box": base_url + "?target=sing-box",
            "surge": base_url + "?target=surge",
            "shadowrocket": base_url + "?target=shadowrocket",
        }

    def subscription_reply_markup(self, config: Dict[str, object], subscription: dict) -> dict:
        urls = self.subscription_format_urls(config, subscription)
        return {
            "inline_keyboard": [
                [
                    {"text": "V2RayNG", "url": urls["v2rayng"]},
                    {"text": "Clash Verge", "url": urls["clash-verge"]},
                ],
                [
                    {"text": "Sing-box", "url": urls["sing-box"]},
                    {"text": "Surge", "url": urls["surge"]},
                ],
                [
                    {"text": "Shadowrocket", "url": urls["shadowrocket"]},
                    {"text": "原始节点", "url": urls["raw"]},
                ],
            ]
        }

    def send_and_record(
        self,
        token: str,
        user_id: str,
        chat_id: str,
        text: str,
        simulate: bool = False,
        reply_markup: dict | None = None,
    ) -> dict:
        if not simulate:
            fields = {
                "chat_id": chat_id,
                "text": text,
            }
            if reply_markup:
                fields["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            self.api(token, "sendMessage", fields)
        with NodeDatabase(self.database) as database:
            database.record_bot_message(user_id, chat_id, "模拟发送" if simulate else "发送", text)
        return {"chat_id": str(chat_id), "text": text, "simulated": simulate, "reply_markup": reply_markup}

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
