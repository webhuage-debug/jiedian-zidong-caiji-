#!/usr/bin/env python3
"""Region rules for nodes that may be published to fan subscriptions."""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from typing import Dict


PRIMARY_ASIA_COUNTRIES = {"HK", "JP", "SG", "TW", "KR"}
US_COUNTRIES = {"US"}
FILLER_ASIA_COUNTRIES = {"MY", "TH", "PH", "VN"}
PUBLISHABLE_COUNTRIES = PRIMARY_ASIA_COUNTRIES | US_COUNTRIES | FILLER_ASIA_COUNTRIES

EXCLUDED_REGION_COUNTRIES = {
    # Europe and explicit exclusions.
    "AD", "AL", "AT", "BA", "BE", "BG", "BY", "CH", "CY", "CZ", "DE", "DK",
    "EE", "ES", "FI", "FR", "GB", "GR", "HR", "HU", "IE", "IS", "IT", "LI",
    "LT", "LU", "LV", "MC", "MD", "ME", "MK", "MT", "NL", "NO", "PL", "PT",
    "RO", "RS", "RU", "SE", "SI", "SK", "SM", "TR", "UA", "UK", "VA",
    # Africa.
    "AO", "BF", "BI", "BJ", "BW", "CD", "CF", "CG", "CI", "CM", "CV", "DJ",
    "DZ", "EG", "ET", "GA", "GH", "GM", "GN", "GQ", "GW", "KE", "LR", "LS",
    "LY", "MA", "MG", "ML", "MR", "MU", "MW", "MZ", "NA", "NE", "NG", "RW",
    "SC", "SD", "SL", "SN", "SO", "SS", "ST", "SZ", "TD", "TG", "TN", "TZ",
    "UG", "ZA", "ZM", "ZW",
    # South Asia, Southeast Asia exclusions, Middle East.
    "AF", "AE", "AM", "AZ", "BD", "BH", "BT", "GE", "ID", "IL", "IN", "IQ",
    "IR", "JO", "KH", "KW", "KZ", "LA", "LB", "LK", "MM", "MN", "NP", "OM",
    "PK", "PS", "QA", "SA", "SY", "TJ", "TL", "TM", "UZ", "YE",
}

PRIMARY_ASIA_KEYWORDS = {
    "hong kong", "\u9999\u6e2f",
    "japan", "\u65e5\u672c", "\u4e1c\u4eac", "tokyo", "osaka", "\u5927\u962a",
    "singapore", "\u65b0\u52a0\u5761",
    "taiwan", "\u53f0\u6e7e",
    "korea", "\u97e9\u56fd", "seoul", "\u9996\u5c14",
}

US_KEYWORDS = {
    "usa", "united states", "\u7f8e\u56fd", "los angeles", "san jose",
    "seattle", "dallas", "new york",
}

FILLER_ASIA_KEYWORDS = {
    "malaysia", "\u9a6c\u6765\u897f\u4e9a",
    "thailand", "\u6cf0\u56fd",
    "philippines", "\u83f2\u5f8b\u5bbe",
    "vietnam", "\u8d8a\u5357",
}

EXCLUDED_KEYWORDS = {
    "united kingdom", "london", "\u82f1\u56fd", "\u4f26\u6566",
    "germany", "\u5fb7\u56fd", "frankfurt",
    "france", "\u6cd5\u56fd", "paris",
    "netherlands", "\u8377\u5170", "amsterdam",
    "russia", "\u4fc4\u7f57\u65af",
    "turkey", "\u571f\u8033\u5176",
    "africa", "south africa", "egypt", "nigeria", "kenya",
    "morocco", "\u975e\u6d32", "\u5357\u975e", "\u57c3\u53ca",
    "india", "\u5370\u5ea6",
    "indonesia", "\u5370\u5c3c",
    "middle east", "dubai", "uae", "iran", "iraq", "israel", "saudi", "qatar",
    "south asia", "pakistan", "bangladesh", "sri lanka", "nepal",
    "unknown", "\u672a\u77e5", "\u672a\u8bc6\u522b",
}

AD_KEYWORDS = {
    "telegram", " t.me/", "https://t.me", "http://t.me", "tg channel", "channel",
    "\u7535\u62a5", "\u9891\u9053", "\u7fa4\u7ec4", "\u5e7f\u544a",
    "join us", "subscribe", "official group",
}

CODE_TO_REGION: Dict[str, str] = {
    **{code: "primary_asia" for code in PRIMARY_ASIA_COUNTRIES},
    **{code: "us" for code in US_COUNTRIES},
    **{code: "filler_asia" for code in FILLER_ASIA_COUNTRIES},
    **{code: "excluded" for code in EXCLUDED_REGION_COUNTRIES},
}


def publish_region(row: Dict[str, object]) -> str:
    if is_advertising_node(row):
        return "excluded"
    country_region = region_from_country(str(row.get("country") or ""))
    if country_region in ("primary_asia", "us", "filler_asia", "excluded"):
        return country_region
    return region_from_text(row_search_text(row))


def is_publishable_region(row: Dict[str, object]) -> bool:
    return publish_region(row) in ("primary_asia", "us", "filler_asia")


def is_collection_candidate(row: Dict[str, object]) -> bool:
    """Return whether a newly collected node is worth entering the pending pool."""
    return is_publishable_region(row)


def publish_region_rank(row: Dict[str, object]) -> int:
    region = publish_region(row)
    if region == "primary_asia":
        return 0
    if region == "us":
        return 1
    if region == "filler_asia":
        return 2
    return 99


def is_advertising_node(row: Dict[str, object]) -> bool:
    text = searchable_text(row_search_text(row)).lower()
    return any(keyword in text for keyword in AD_KEYWORDS)


def row_search_text(row: Dict[str, object]) -> str:
    parts = [
        str(row.get("uri") or ""),
        str(row.get("name") or ""),
        str(row.get("remark") or ""),
        str(row.get("tag") or ""),
        str(row.get("server_name") or ""),
        str(row.get("source") or ""),
        str(row.get("repo") or ""),
        str(row.get("encoding") or ""),
    ]
    return " ".join(part for part in parts if part)


def region_from_country(country: str) -> str:
    parts = [part.strip().upper() for part in (country or "").split(",") if part.strip()]
    for part in parts:
        normalized = "UK" if part == "GB" else part
        region = CODE_TO_REGION.get(normalized)
        if region:
            return region
    return "unknown"


def region_from_text(value: str) -> str:
    text = searchable_text(value)
    lower = text.lower()
    if any(keyword in lower for keyword in AD_KEYWORDS):
        return "excluded"
    code_region = region_from_codes(text)
    if code_region != "unknown":
        return code_region
    if any(keyword in lower for keyword in EXCLUDED_KEYWORDS):
        return "excluded"
    if any(keyword in lower for keyword in PRIMARY_ASIA_KEYWORDS):
        return "primary_asia"
    if any(keyword in lower for keyword in US_KEYWORDS):
        return "us"
    if any(keyword in lower for keyword in FILLER_ASIA_KEYWORDS):
        return "filler_asia"
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
    for region in ("excluded", "primary_asia", "us", "filler_asia"):
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
