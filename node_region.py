#!/usr/bin/env python3
"""Region rules for publishable subscription nodes."""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from typing import Dict


PUBLISHABLE_ASIA_COUNTRIES = {"JP", "SG", "HK", "TW", "KR", "MY", "TH", "VN", "PH"}
PUBLISHABLE_US_COUNTRIES = {"US"}
PUBLISHABLE_COUNTRIES = PUBLISHABLE_ASIA_COUNTRIES | PUBLISHABLE_US_COUNTRIES

EXCLUDED_REGION_COUNTRIES = {
    "GB", "UK", "DE", "FR", "NL", "RU", "TR",
    "ZA", "EG", "NG", "KE", "MA",
}

ASIA_KEYWORDS = {
    "japan", "日本", "东京", "tokyo", "osaka", "大阪",
    "singapore", "新加坡",
    "hong kong", "香港",
    "taiwan", "台湾",
    "korea", "韩国", "seoul", "首尔",
    "malaysia", "马来西亚",
    "thailand", "泰国",
    "vietnam", "越南",
    "philippines", "菲律宾",
}

US_KEYWORDS = {
    "usa", "united states", "美国", "los angeles", "san jose",
    "seattle", "dallas", "new york",
}

EUROPE_KEYWORDS = {
    "united kingdom", "london", "英国", "伦敦",
    "germany", "德国", "frankfurt",
    "france", "法国", "paris",
    "netherlands", "荷兰", "amsterdam",
    "russia", "俄罗斯",
    "turkey", "土耳其",
}

AFRICA_KEYWORDS = {
    "africa", "south africa", "egypt", "nigeria", "kenya", "morocco",
    "非洲", "南非", "埃及",
}

CODE_TO_REGION: Dict[str, str] = {
    **{code: "asia" for code in PUBLISHABLE_ASIA_COUNTRIES},
    **{code: "us" for code in PUBLISHABLE_US_COUNTRIES},
    **{code: "excluded" for code in EXCLUDED_REGION_COUNTRIES},
}


def publish_region(row: Dict[str, object]) -> str:
    country_region = region_from_country(str(row.get("country") or ""))
    if country_region in ("asia", "us", "excluded"):
        return country_region
    return region_from_text(str(row.get("uri") or ""))


def is_publishable_region(row: Dict[str, object]) -> bool:
    return publish_region(row) in ("asia", "us")


def publish_region_rank(row: Dict[str, object]) -> int:
    region = publish_region(row)
    if region == "asia":
        return 0
    if region == "us":
        return 1
    return 99


def region_from_country(country: str) -> str:
    parts = [part.strip().upper() for part in (country or "").split(",") if part.strip()]
    for part in parts:
        region = CODE_TO_REGION.get("UK" if part == "GB" else part)
        if region:
            return region
    return "unknown"


def region_from_text(value: str) -> str:
    text = searchable_text(value)
    lower = text.lower()
    code_region = region_from_codes(text)
    if code_region != "unknown":
        return code_region
    if any(keyword in lower for keyword in ASIA_KEYWORDS):
        return "asia"
    if any(keyword in lower for keyword in US_KEYWORDS):
        return "us"
    if any(keyword in lower for keyword in EUROPE_KEYWORDS):
        return "excluded"
    if any(keyword in lower for keyword in AFRICA_KEYWORDS):
        return "excluded"
    return "unknown"


def region_from_codes(text: str) -> str:
    found = []
    for match in re.finditer(r"(?<![A-Za-z0-9])([A-Za-z]{2})(?![A-Za-z0-9])", text):
        code = match.group(1).upper()
        if code == "LA":
            found.append("us")
            continue
        region = CODE_TO_REGION.get("UK" if code == "GB" else code)
        if region:
            found.append(region)
    for region in ("excluded", "asia", "us"):
        if region in found:
            return region
    return "unknown"


def searchable_text(uri: str) -> str:
    decoded = urllib.parse.unquote(str(uri or ""))
    parts = [decoded]
    parsed = urllib.parse.urlsplit(decoded)
    if parsed.hostname:
        parts.append(parsed.hostname)
    if parsed.fragment:
        parts.append(parsed.fragment)
    if decoded.lower().startswith("vmess://"):
        parts.extend(vmess_text(decoded))
    return " ".join(part for part in parts if part)


def vmess_text(uri: str) -> list[str]:
    payload = uri.split("://", 1)[1].split("#", 1)[0]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    keys = ("ps", "name", "add", "host", "sni")
    return [str(data.get(key) or "") for key in keys if data.get(key)]
