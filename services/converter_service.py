"""Sub-Store conversion helpers."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List


SUB_STORE_PROJECT_URL = "https://github.com/sub-store-org/Sub-Store"
SUBSCRIPTION_EXPORT_MAX = 80
SUB_STORE_TARGETS = {
    "v2rayng": {"name": "V2RayNG", "target": "V2Ray"},
    "clash-verge": {"name": "Clash Verge", "target": "ClashMeta"},
    "sing-box": {"name": "Sing-box", "target": "sing-box"},
    "surge": {"name": "Surge", "target": "Surge"},
    "shadowrocket": {"name": "Shadowrocket 小火箭", "target": "Shadowrocket"},
}
SUB_STORE_INPUT_TYPES = {
    "auto": "自动识别",
    "mixed": "混合节点",
    "vless": "VLESS",
    "vmess": "VMess",
    "trojan": "Trojan",
    "ss": "Shadowsocks",
    "socks": "SOCKS",
    "base64": "Base64 订阅",
    "url": "订阅 URL",
}


def sub_store_unreachable_message(backend_url: object, reason: object) -> str:
    url = str(backend_url or "").strip() or "未配置"
    return (
        "Sub-Store 服务不可达: "
        + str(reason)
        + "；当前地址 "
        + url
        + "。请先启动 Sub-Store sidecar，或在订阅转换页面修正服务地址。"
    )


def subscription_converter_targets() -> List[dict]:
    return [
        {"id": key, "name": value["name"], "target": value["target"]}
        for key, value in SUB_STORE_TARGETS.items()
    ]


def subscription_converter_input_types() -> List[dict]:
    return [{"id": key, "name": value} for key, value in SUB_STORE_INPUT_TYPES.items()]


def _backend_url(config: dict) -> str:
    backend_url = str(config.get("backend_url") or "").strip().rstrip("/")
    if not backend_url.startswith(("http://", "https://")):
        raise ValueError("Sub-Store 服务地址必须以 http:// 或 https:// 开头")
    return backend_url


def _base_profile_name(config: dict) -> str:
    profile_name = str(config.get("profile_name") or "sub").strip().strip("/") or "sub"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", profile_name).strip(".-") or "sub"


def temporary_profile_name(config: dict, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return (_base_profile_name(config) + "-huage-" + digest)[:96]


def sub_store_download_url(config: dict, target_id: str, content: str = "") -> str:
    if target_id not in SUB_STORE_TARGETS:
        raise ValueError("不支持的订阅转换目标")
    profile_name = temporary_profile_name(config, content) if content else _base_profile_name(config)
    query = urllib.parse.urlencode({"target": SUB_STORE_TARGETS[target_id]["target"]})
    return _backend_url(config) + "/download/" + urllib.parse.quote(profile_name, safe="/") + "?" + query


def _read_json_response(response) -> dict:
    raw = response.read()
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def ensure_sub_store_profile(config: dict, content: str = "vmess://", timeout: int = 8) -> dict:
    backend_url = _backend_url(config)
    profile_name = temporary_profile_name(config, content)
    headers = {"User-Agent": "HuageNodeDashboard/1.0"}
    list_request = urllib.request.Request(backend_url + "/api/subs", headers=headers)
    with urllib.request.urlopen(list_request, timeout=timeout) as response:
        payload = _read_json_response(response)
    subs = payload.get("data") if isinstance(payload, dict) else []
    if isinstance(subs, list):
        for item in subs:
            if isinstance(item, dict) and str(item.get("name") or "") == profile_name:
                return {"profile_name": profile_name, "created": False}

    body = json.dumps(
        {
            "name": profile_name,
            "displayName": "Huage Temporary",
            "source": "local",
            "sourceType": "local",
            "url": "",
            "content": content,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    create_request = urllib.request.Request(
        backend_url + "/api/subs",
        data=body,
        method="POST",
        headers={**headers, "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(create_request, timeout=timeout) as response:
        response.read()
    return {"profile_name": profile_name, "created": True}


def delete_sub_store_profile(config: dict, profile_name: str, timeout: int = 8) -> None:
    try:
        backend_url = _backend_url(config)
    except ValueError:
        return
    url = backend_url + "/api/sub/" + urllib.parse.quote(profile_name, safe="")
    request = urllib.request.Request(url, method="DELETE", headers={"User-Agent": "HuageNodeDashboard/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise


def convert_with_sub_store(config: dict, target_id: str, content: str, timeout: int = 25) -> dict:
    content = content.strip()
    if target_id not in SUB_STORE_TARGETS:
        raise ValueError("不支持的订阅转换目标")
    if not content:
        raise ValueError("订阅转换内容不能为空")
    profile = ensure_sub_store_profile(config, content)
    profile_name = str(profile["profile_name"])
    body = b""
    try:
        url = sub_store_download_url(config, target_id, content)
        request = urllib.request.Request(url, headers={"User-Agent": "HuageNodeDashboard/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    finally:
        delete_sub_store_profile(config, profile_name)
    text = body.decode("utf-8", errors="replace")
    target = SUB_STORE_TARGETS[target_id]
    return {
        "target": target["name"],
        "target_id": target_id,
        "sub_store_target": target["target"],
        "content": text,
        "bytes": len(body),
        "source": "Sub-Store lightweight API",
        "profile_name": profile_name,
        "project_url": SUB_STORE_PROJECT_URL,
    }


def subscription_conversion_cache_identity(
    config: dict,
    target_id: str,
    content: str,
    input_mode: str,
    input_type: str,
    claim_code_version: str,
) -> dict:
    node_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    identity = {
        "claim_code_version": str(claim_code_version or ""),
        "target_id": target_id,
        "node_hash": node_hash,
        "input_mode": input_mode,
        "input_type": input_type,
        "export_limit": min(int(config.get("export_limit") or SUBSCRIPTION_EXPORT_MAX), SUBSCRIPTION_EXPORT_MAX),
        "prefer_asia": bool(config.get("prefer_asia")),
        "backend_url": str(config.get("backend_url") or "").strip().rstrip("/"),
        "profile_name": _base_profile_name(config),
    }
    cache_key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"cache_key": cache_key, "node_hash": node_hash, "identity": identity}


def check_sub_store_health(config: dict, timeout: int = 5) -> dict:
    backend_url = _backend_url(config)
    started = time.monotonic()
    request = urllib.request.Request(backend_url + "/", headers={"User-Agent": "HuageNodeDashboard/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 0) or response.getcode() or 0)
            ok = 200 <= status_code < 500
            message = "Sub-Store 服务可达，HTTP " + str(status_code)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        ok = status_code < 500
        message = "Sub-Store 服务可达，HTTP " + str(status_code)
    seconds = time.monotonic() - started
    return {
        "ok": ok,
        "backend_url": backend_url,
        "status_code": status_code,
        "message": message,
        "latency_ms": round(seconds * 1000, 2),
    }
