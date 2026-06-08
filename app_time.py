#!/usr/bin/env python3
"""Beijing time helpers used by the application and SQLite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
SQL_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def beijing_timestamp() -> str:
    return beijing_now().strftime(SQL_DATETIME_FORMAT)


def beijing_date() -> str:
    return beijing_now().strftime("%Y-%m-%d")


def beijing_time() -> str:
    return beijing_now().strftime("%H:%M:%S")
