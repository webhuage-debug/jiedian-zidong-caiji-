#!/usr/bin/env python3
"""Final subscription node filtering and ordering."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List

from node_region import is_publishable_region, publish_region_rank


DEFAULT_SUBSCRIPTION_TARGET = 30
MIN_SUBSCRIPTION_TARGET = 15
MAX_SUBSCRIPTION_TARGET = 80


def normalize_subscription_limit(value: object, default: int = DEFAULT_SUBSCRIPTION_TARGET) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, MAX_SUBSCRIPTION_TARGET))


def final_subscription_nodes(nodes: Iterable[Dict[str, object]], limit: object = DEFAULT_SUBSCRIPTION_TARGET) -> List[Dict[str, object]]:
    target = normalize_subscription_limit(limit)
    rows = [dict(row) for row in nodes if is_publishable_region(row)]
    return sorted(rows, key=subscription_sort_key)[:target]


def subscription_sort_key(row: Dict[str, object]) -> tuple:
    return (
        -subscription_quality_score(row),
        publish_region_rank(row),
        recent_first_key(row.get("last_validated")),
        float(row.get("seconds") or 9999.0),
        str(row.get("uri") or ""),
    )


def subscription_quality_score(row: Dict[str, object]) -> float:
    """Score publishable nodes without letting London VPS latency dominate."""
    rank = publish_region_rank(row)
    region_score = 300.0 if rank == 0 else 220.0 if rank == 1 else 150.0 if rank == 2 else 0.0
    validations = min(max(int(row.get("validation_count") or 0), 0), 20)
    stability_score = validations * 18.0
    latency = max(float(row.get("seconds") or 9999.0), 0.0)
    latency_score = max(0.0, 260.0 - latency * 85.0)
    high_latency_penalty = max(0.0, latency - 2.0) * 90.0
    base_score = float(row.get("premium_score") or row.get("quality_score") or 0)
    return round(region_score + stability_score + latency_score + base_score * 0.05 - high_latency_penalty, 2)


def recent_first_key(value: object) -> tuple:
    numbers = [int(item) for item in re.findall(r"\d+", str(value or ""))[:6]]
    while len(numbers) < 6:
        numbers.append(0)
    return tuple(-item for item in numbers)
