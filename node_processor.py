#!/usr/bin/env python3
"""Prepare valid proxy nodes for renamed subscription export."""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from typing import Dict, Iterable, List

from app_time import beijing_date

DEFAULT_RENAME_TEMPLATE = "{country_name} {protocol} {validated_date} #{index}"
MAX_NODE_NAME_LENGTH = 80

COUNTRY_NAMES_ZH = {
    "AD": "安道尔", "AE": "阿联酋", "AF": "阿富汗", "AG": "安提瓜和巴布达", "AI": "安圭拉",
    "AL": "阿尔巴尼亚", "AM": "亚美尼亚", "AO": "安哥拉", "AR": "阿根廷", "AS": "美属萨摩亚",
    "AT": "奥地利", "AU": "澳大利亚", "AW": "阿鲁巴", "AZ": "阿塞拜疆", "BA": "波黑",
    "BB": "巴巴多斯", "BD": "孟加拉国", "BE": "比利时", "BF": "布基纳法索", "BG": "保加利亚",
    "BH": "巴林", "BI": "布隆迪", "BJ": "贝宁", "BM": "百慕大", "BN": "文莱",
    "BO": "玻利维亚", "BR": "巴西", "BS": "巴哈马", "BT": "不丹", "BW": "博茨瓦纳",
    "BY": "白俄罗斯", "BZ": "伯利兹", "CA": "加拿大", "CD": "刚果金", "CF": "中非",
    "CG": "刚果", "CH": "瑞士", "CI": "科特迪瓦", "CL": "智利", "CM": "喀麦隆",
    "CN": "中国", "CO": "哥伦比亚", "CR": "哥斯达黎加", "CU": "古巴", "CV": "佛得角",
    "CY": "塞浦路斯", "CZ": "捷克", "DE": "德国", "DJ": "吉布提", "DK": "丹麦",
    "DM": "多米尼克", "DO": "多米尼加", "DZ": "阿尔及利亚", "EC": "厄瓜多尔", "EE": "爱沙尼亚",
    "EG": "埃及", "ES": "西班牙", "ET": "埃塞俄比亚", "FI": "芬兰", "FJ": "斐济",
    "FM": "密克罗尼西亚", "FR": "法国", "GA": "加蓬", "GB": "英国", "GD": "格林纳达",
    "GE": "格鲁吉亚", "GH": "加纳", "GI": "直布罗陀", "GM": "冈比亚", "GN": "几内亚",
    "GQ": "赤道几内亚", "GR": "希腊", "GT": "危地马拉", "GU": "关岛", "GW": "几内亚比绍",
    "GY": "圭亚那", "HK": "中国香港", "HN": "洪都拉斯", "HR": "克罗地亚", "HT": "海地",
    "HU": "匈牙利", "ID": "印度尼西亚", "IE": "爱尔兰", "IL": "以色列", "IN": "印度",
    "IQ": "伊拉克", "IR": "伊朗", "IS": "冰岛", "IT": "意大利", "JM": "牙买加",
    "JO": "约旦", "JP": "日本", "KE": "肯尼亚", "KG": "吉尔吉斯斯坦", "KH": "柬埔寨",
    "KI": "基里巴斯", "KM": "科摩罗", "KN": "圣基茨和尼维斯", "KP": "朝鲜", "KR": "韩国",
    "KW": "科威特", "KZ": "哈萨克斯坦", "LA": "老挝", "LB": "黎巴嫩", "LC": "圣卢西亚",
    "LI": "列支敦士登", "LK": "斯里兰卡", "LR": "利比里亚", "LS": "莱索托", "LT": "立陶宛",
    "LU": "卢森堡", "LV": "拉脱维亚", "LY": "利比亚", "MA": "摩洛哥", "MC": "摩纳哥",
    "MD": "摩尔多瓦", "ME": "黑山", "MG": "马达加斯加", "MH": "马绍尔群岛", "MK": "北马其顿",
    "ML": "马里", "MM": "缅甸", "MN": "蒙古", "MO": "中国澳门", "MR": "毛里塔尼亚",
    "MT": "马耳他", "MU": "毛里求斯", "MV": "马尔代夫", "MW": "马拉维", "MX": "墨西哥",
    "MY": "马来西亚", "MZ": "莫桑比克", "NA": "纳米比亚", "NE": "尼日尔", "NG": "尼日利亚",
    "NI": "尼加拉瓜", "NL": "荷兰", "NO": "挪威", "NP": "尼泊尔", "NZ": "新西兰",
    "OM": "阿曼", "PA": "巴拿马", "PE": "秘鲁", "PG": "巴布亚新几内亚", "PH": "菲律宾",
    "PK": "巴基斯坦", "PL": "波兰", "PR": "波多黎各", "PS": "巴勒斯坦", "PT": "葡萄牙",
    "PY": "巴拉圭", "QA": "卡塔尔", "RO": "罗马尼亚", "RS": "塞尔维亚", "RU": "俄罗斯",
    "RW": "卢旺达", "SA": "沙特阿拉伯", "SB": "所罗门群岛", "SC": "塞舌尔", "SD": "苏丹",
    "SE": "瑞典", "SG": "新加坡", "SI": "斯洛文尼亚", "SK": "斯洛伐克", "SL": "塞拉利昂",
    "SM": "圣马力诺", "SN": "塞内加尔", "SO": "索马里", "SR": "苏里南", "SS": "南苏丹",
    "ST": "圣多美和普林西比", "SV": "萨尔瓦多", "SY": "叙利亚", "SZ": "斯威士兰", "TD": "乍得",
    "TG": "多哥", "TH": "泰国", "TJ": "塔吉克斯坦", "TL": "东帝汶", "TM": "土库曼斯坦",
    "TN": "突尼斯", "TO": "汤加", "TR": "土耳其", "TT": "特立尼达和多巴哥", "TW": "中国台湾",
    "TZ": "坦桑尼亚", "UA": "乌克兰", "UG": "乌干达", "US": "美国", "UY": "乌拉圭",
    "UZ": "乌兹别克斯坦", "VA": "梵蒂冈", "VC": "圣文森特和格林纳丁斯", "VE": "委内瑞拉",
    "VN": "越南", "VU": "瓦努阿图", "WS": "萨摩亚", "YE": "也门", "ZA": "南非",
    "ZM": "赞比亚", "ZW": "津巴布韦",
}


def b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def b64_encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii").rstrip("=")


def country_name(country: str) -> str:
    parts = [item.strip().upper() for item in (country or "").split(",") if item.strip()]
    if not parts:
        return "未知地区"
    return "/".join(COUNTRY_NAMES_ZH.get(item, item) for item in parts)


def first_proxy_ip(proxy_ips: str) -> str:
    return (proxy_ips or "").split(",", 1)[0].strip()


def date_part(value: str) -> str:
    return (value or "").split(" ", 1)[0] or beijing_date()


def template_variables(node: Dict[str, object], index: int, export_date: str) -> Dict[str, str]:
    protocol = str(node.get("protocol") or "").lower()
    country = str(node.get("country") or "").upper()
    last_validated = str(node.get("last_validated") or "")
    proxy_ips = str(node.get("proxy_ips") or "")
    seconds = float(node.get("seconds") or 0)
    return {
        "index": f"{index:03d}",
        "index_raw": str(index),
        "protocol": protocol.upper(),
        "protocol_lower": protocol,
        "country": country or "未知",
        "country_name": country_name(country),
        "proxy_ip": first_proxy_ip(proxy_ips) or "未知出口",
        "proxy_ips": proxy_ips or "未知出口",
        "latency": f"{seconds:.2f}",
        "date": export_date,
        "validated_at": last_validated or "未知验证时间",
        "validated_date": date_part(last_validated),
    }


def render_name(template: str, node: Dict[str, object], index: int, export_date: str) -> str:
    variables = template_variables(node, index, export_date)

    def replace(match: re.Match[str]) -> str:
        return variables.get(match.group(1), match.group(0))

    name = re.sub(r"\{([a-zA-Z0-9_]+)\}", replace, template or DEFAULT_RENAME_TEMPLATE)
    return " ".join(name.split())


def clean_node_name(value: str, index: int, max_length: int = MAX_NODE_NAME_LENGTH) -> str:
    name = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    name = " ".join(name.split()).strip()
    if not name:
        name = "Node " + f"{index:03d}"
    return truncate_node_name(name, max_length)


def truncate_node_name(value: str, max_length: int = MAX_NODE_NAME_LENGTH) -> str:
    max_length = max(16, int(max_length or MAX_NODE_NAME_LENGTH))
    return str(value or "")[:max_length].strip() or "Node"


def unique_node_name(base_name: str, index: int, seen: Dict[str, int], max_length: int = MAX_NODE_NAME_LENGTH) -> str:
    base = clean_node_name(base_name, index, max_length)
    count = seen.get(base, 0) + 1
    seen[base] = count
    if count == 1:
        return base
    suffix = " #" + str(count)
    return truncate_node_name(base, max_length - len(suffix)) + suffix


def set_url_fragment(uri: str, name: str) -> str:
    fragment = urllib.parse.quote(name, safe="")
    return uri.split("#", 1)[0] + "#" + fragment


def rename_vmess(uri: str, name: str) -> str:
    payload = uri.split("://", 1)[1].split("#", 1)[0]
    data = json.loads(b64_decode(payload).decode("utf-8"))
    data["ps"] = name
    data["name"] = name
    encoded = b64_encode(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return "vmess://" + encoded


def rename_node(uri: str, name: str) -> str:
    protocol = uri.split("://", 1)[0].lower() if "://" in uri else ""
    try:
        if protocol == "vmess":
            return rename_vmess(uri, name)
        if protocol in {"vless", "trojan", "ss", "socks", "socks5", "hysteria2", "hy2", "tuic", "wireguard"}:
            return set_url_fragment(uri, name)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return set_url_fragment(uri, name)
    return set_url_fragment(uri, name)


def processed_nodes(nodes: Iterable[Dict[str, object]], template: str) -> List[Dict[str, str]]:
    export_date = beijing_date()
    rows = []
    seen_names: Dict[str, int] = {}
    for index, node in enumerate(nodes, 1):
        name = unique_node_name(render_name(template, node, index, export_date), index, seen_names)
        rows.append({
            "name": name,
            "protocol": str(node.get("protocol") or "").upper(),
            "country": str(node.get("country") or ""),
            "proxy_ips": str(node.get("proxy_ips") or ""),
            "uri": rename_node(str(node.get("uri") or ""), name),
            "original_uri": str(node.get("uri") or ""),
        })
    return rows


def subscription_base64_from_rows(rows: Iterable[Dict[str, str]]) -> Dict[str, object]:
    rows = list(rows)
    plain = "\n".join(row["uri"] for row in rows)
    encoded = base64.b64encode(plain.encode("utf-8")).decode("ascii")
    return {"subscription": encoded, "count": len(rows), "plain_bytes": len(plain.encode("utf-8"))}


def subscription_base64(nodes: Iterable[Dict[str, object]], template: str) -> Dict[str, object]:
    rows = processed_nodes(nodes, template)
    return subscription_base64_from_rows(rows)
