def system_health_summary(database_stats: dict, control: dict, tasks: dict) -> dict:
    config = control.get("config") or {}
    valid_count = int(database_stats.get("valid_nodes") or 0)
    pending_count = int(database_stats.get("pending_nodes", database_stats.get("total_nodes", 0)) or 0)
    invalid_count = int(database_stats.get("invalid_nodes") or 0)
    all_count = max(1, int(database_stats.get("all_nodes", database_stats.get("total_nodes", 0)) or 0))
    valid_target = max(1, int(config.get("valid_low_watermark") or 1000))
    invalid_percent = min(100.0, (invalid_count / all_count) * 100)
    collector_running = bool(tasks.get("collector", {}).get("running"))
    validator_running = bool(tasks.get("validator", {}).get("running"))
    valid_ratio = min(1.0, valid_count / valid_target)
    score = round(valid_ratio * 58)
    if pending_count > 0:
        score += 14
    if control.get("enabled"):
        score += 12
    if validator_running or collector_running:
        score += 8
    score += max(0, round(8 - invalid_percent / 5))
    score = max(0, min(100, score))
    level = "ok" if score >= 80 else "warning" if score >= 55 else "error"
    if valid_count < valid_target * 0.2 and pending_count > 0:
        status = "需补货"
        recommendation = "继续验证" if validator_running else "优先验证"
        summary = f"当前有效节点 {valid_count:,} / {valid_target:,}，库存明显不足；待验证节点充足，建议优先验证，不需要先采集。"
        risks = ["有效节点严重不足", "待验证库存充足"]
    elif valid_count < valid_target and pending_count <= 0:
        status = "需采集"
        recommendation = "继续采集" if collector_running else "启动采集"
        summary = "当前有效节点低于目标，且未验证库存为空，建议启动采集补充节点池。"
        risks = ["有效节点不足", "待验证库存为空"]
    elif invalid_percent >= 35:
        status = "质量告警"
        recommendation = "清理无效"
        summary = f"无效节点占比 {invalid_percent:.1f}%，质量风险偏高，建议继续复检并清理失效节点。"
        risks = ["无效节点占比偏高"]
    elif valid_count >= valid_target:
        status = "自动健康" if control.get("enabled") else "库存健康"
        recommendation = "保持巡检" if control.get("enabled") else "开启总控"
        summary = "有效节点已达到目标，当前库存健康；建议保持自动巡检，持续剔除失效节点。"
        risks = []
    else:
        status = "验证中" if validator_running else "观察中"
        recommendation = "继续验证" if pending_count > 0 else "等待补货"
        summary = "有效节点尚未达到目标，但系统仍有可用库存；建议按当前策略继续推进。"
        risks = ["有效节点未达目标"]
    return {
        "score": score,
        "level": level,
        "status": status,
        "recommendation": recommendation,
        "summary": summary,
        "risks": risks,
        "metrics": {
            "valid_count": valid_count,
            "pending_count": pending_count,
            "invalid_count": invalid_count,
            "all_count": all_count,
            "valid_target": valid_target,
            "invalid_percent": round(invalid_percent, 1),
        },
    }
