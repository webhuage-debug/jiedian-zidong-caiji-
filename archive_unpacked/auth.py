#!/usr/bin/env python3
"""Admin authentication helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from http.cookies import SimpleCookie
from typing import Optional

from app_config import CONFIG
from app_time import beijing_now
from node_database import NodeDatabase


COOKIE_NAME = "huage_admin_session"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin888"
HASH_ITERATIONS = 260_000
SESSION_DAYS = 7


def hash_password(password: str, salt: Optional[bytes] = None, iterations: int = HASH_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        method, iterations, salt_text, digest_text = stored_hash.split("$", 3)
        if method != "pbkdf2_sha256":
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def ensure_default_admin(database: NodeDatabase) -> None:
    database.ensure_admin_user(DEFAULT_USERNAME, hash_password(DEFAULT_PASSWORD))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(database: NodeDatabase, user_id: int, ip: str, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = beijing_now() + timedelta(days=SESSION_DAYS)
    database.create_admin_session(
        token_hash(token),
        user_id,
        expires_at.strftime("%Y-%m-%d %H:%M:%S"),
        ip,
        user_agent,
    )
    return token


def cookie_header(token: str, secure: bool) -> str:
    parts = [
        COOKIE_NAME + "=" + token,
        "Path=" + CONFIG.admin_base_path,
        "Max-Age=" + str(SESSION_DAYS * 24 * 60 * 60),
        "HttpOnly",
        "SameSite=Lax",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie_header() -> str:
    return COOKIE_NAME + "=; Path=" + CONFIG.admin_base_path + "; Max-Age=0; HttpOnly; SameSite=Lax"


def cookie_token(cookie_header_value: str) -> str:
    if not cookie_header_value:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header_value)
    except Exception:
        return ""
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel else ""


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
