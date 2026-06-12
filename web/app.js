const $ = (id) => document.getElementById(id);
let page = 1;
let nodeTotal = 0;
let logFilter = "all";
const logEvents = [];
const nodePageSize = 20;
let moduleSnapshot = null;
let moduleSnapshotAt = Date.now();
const BASE_PATH = window.location.pathname.startsWith("/adminhuage") ? "/adminhuage" : "";
const APP_TITLE_PREFIX = "\u534e\u54e5\u8282\u70b9\u603b\u63a7\u4eea\u8868\u76d8";
let currentUser = null;
let eventSource = null;
let lastDatabaseSnapshot = null;
let currentSubscriptions = [];
const PAGE_META = {
  navDashboard: ["总控仪表盘", "系统状态、风险判断、自动调度、趋势与总日志集中展示。"],
  navCollect: ["采集工作台", "管理采集源、启动采集任务、查看采集进度和来源画像。"],
  navValidate: ["验证工作台", "调用 Xray 验证节点连通性、延迟、出口和有效性。"],
  navNodes: ["节点资产库", "查看有效节点、筛选协议国家、预览命名并导出原始节点。"],
  navSubscription: ["订阅分发中心", "管理订阅链接、调用 Sub-Store 转换格式并查看转换日志。"],
  navBot: ["口令与 BOT", "配置领取口令、Telegram BOT、群组触发和完整模拟测试。"],
  navSettings: ["系统设置", "真实验收、维护清理、缓存策略和长期运行配置集中管理。"],
};

function api(path) {
  return `${BASE_PATH}${path}`;
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 2600);
}

function formatBytes(bytes = 0) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...options });
  if (response.status === 401) {
    redirectToLogin();
  }
  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = payload.reason || payload.error || payload.message || "";
    } catch (error) {
      detail = "";
    }
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return response.json();
}

function taskBadge(id, running) {
  const badge = $(id);
  badge.textContent = running ? "运行中" : "已停止";
  badge.classList.toggle("running", running);
}

function setLight(id, active, warning = false) {
  const light = $(id);
  light.classList.toggle("active", active);
  light.classList.toggle("warning", warning);
}

function setButtonLight(id, state = "off") {
  const button = $(id);
  if (!button) return;
  let light = button.querySelector(".button-light");
  if (!light) {
    light = document.createElement("span");
    light.className = "button-light";
    light.setAttribute("aria-hidden", "true");
    button.prepend(light);
  }
  light.className = `button-light ${state === "off" ? "" : state}`.trim();
}

function setGauge(id, percent, state = "ok") {
  const gauge = $(id);
  if (!gauge) return;
  const safePercent = Math.max(0, Math.min(100, Number(percent || 0)));
  const colors = {
    ok: "var(--success)",
    running: "var(--accent)",
    warning: "var(--warning)",
    error: "var(--danger)",
  };
  gauge.style.setProperty("--gauge-deg", `${safePercent * 1.8}deg`);
  gauge.style.setProperty("--gauge-color", colors[state] || colors.ok);
}

function healthState(score) {
  if (score >= 80) return "ok";
  if (score >= 55) return "warning";
  return "error";
}

function validInventoryState(validCount, validTarget) {
  if (validCount >= validTarget) return "库存健康";
  if (validCount >= validTarget * 0.5) return "库存偏低";
  return "严重不足";
}

function pendingPressureState(pendingCount, pendingTarget) {
  if (pendingCount <= 0) return "无压力";
  if (pendingCount >= pendingTarget * 0.6) return "压力高";
  if (pendingCount >= pendingTarget * 0.2) return "压力中";
  return "压力低";
}

function dashboardMetrics(data, auto) {
  const database = data.database || {};
  const validCount = Number(database.valid_nodes || 0);
  const pendingCount = Number(database.pending_nodes ?? database.total_nodes ?? 0);
  const invalidCount = Number(database.invalid_nodes || 0);
  const allCount = Math.max(1, Number(database.all_nodes ?? database.total_nodes ?? 0));
  const validTarget = Math.max(1, Number(auto.config?.valid_low_watermark || 1000));
  const pendingTarget = Math.max(1, Number(auto.config?.collect_insert_target || 20000));
  const invalidPercent = Math.min(100, (invalidCount / allCount) * 100);
  return { validCount, pendingCount, invalidCount, allCount, validTarget, pendingTarget, invalidPercent };
}

function cockpitDecision({ validCount, pendingCount, invalidPercent, validTarget, auto, collectorRunning, validatorRunning }) {
  const validRatio = Math.min(1, validCount / validTarget);
  let score = Math.round(validRatio * 58);
  if (pendingCount > 0) score += 14;
  if (auto.enabled) score += 12;
  if (validatorRunning || collectorRunning) score += 8;
  score += Math.max(0, Math.round(8 - invalidPercent / 5));
  score = Math.max(0, Math.min(100, score));
  if (validCount < validTarget * 0.2 && pendingCount > 0) {
    return {
      score,
      status: "需补货",
      action: validatorRunning ? "继续验证" : "优先验证",
      summary: `当前有效节点 ${validCount.toLocaleString()} / ${validTarget.toLocaleString()}，库存明显不足；待验证节点充足，建议优先验证，不需要先采集。`,
    };
  }
  if (validCount < validTarget && pendingCount <= 0) {
    return {
      score,
      status: "需采集",
      action: collectorRunning ? "继续采集" : "启动采集",
      summary: `当前有效节点低于目标，且未验证库存为空，建议启动采集补充节点池。`,
    };
  }
  if (invalidPercent >= 35) {
    return {
      score,
      status: "质量告警",
      action: "清理无效",
      summary: `无效节点占比 ${invalidPercent.toFixed(1)}%，质量风险偏高，建议继续复检并清理失效节点。`,
    };
  }
  if (validCount >= validTarget) {
    return {
      score,
      status: auto.enabled ? "自动健康" : "库存健康",
      action: auto.enabled ? "保持巡检" : "开启总控",
      summary: `有效节点已达到目标，当前库存健康；建议保持自动巡检，持续剔除失效节点。`,
    };
  }
  return {
    score,
    status: validatorRunning ? "验证中" : "观察中",
    action: pendingCount > 0 ? "继续验证" : "等待补货",
    summary: `有效节点尚未达到目标，但系统仍有可用库存；建议按当前策略继续推进。`,
  };
}

function cockpitDecisionFromStatus(data, metrics, auto, collectorRunning, validatorRunning) {
  const summary = data.system_health;
  if (!summary) {
    return cockpitDecision({ ...metrics, auto, collectorRunning, validatorRunning });
  }
  return {
    score: Number(summary.score || 0),
    status: summary.status || "观察中",
    action: summary.recommendation || "等待判断",
    summary: summary.summary || "系统状态已同步。",
  };
}

function updateCockpit(data, auto, collectorRunning, validatorRunning) {
  const metrics = dashboardMetrics(data, auto);
  const decision = cockpitDecisionFromStatus(data, metrics, auto, collectorRunning, validatorRunning);
  const decisionState = healthState(decision.score);
  setGauge("healthGauge", decision.score, decisionState);
  setGauge("validGauge", (metrics.validCount / metrics.validTarget) * 100, metrics.validCount >= metrics.validTarget ? "ok" : metrics.validCount >= metrics.validTarget * 0.5 ? "warning" : "error");
  setGauge("pendingGauge", (metrics.pendingCount / metrics.pendingTarget) * 100, metrics.pendingCount > 0 ? "running" : "ok");
  $("healthScore").textContent = decision.score;
  $("healthGaugeLabel").textContent = decision.status;
  $("healthGaugeState").textContent = decision.status;
  $("cockpitBadge").textContent = decision.status;
  $("cockpitBadge").classList.toggle("running", decisionState === "ok");
  $("cockpitSummary").textContent = decision.summary;
  $("cockpitAction").textContent = decision.action;
  $("validGaugeState").textContent = validInventoryState(metrics.validCount, metrics.validTarget);
  $("pendingGaugeState").textContent = pendingPressureState(metrics.pendingCount, metrics.pendingTarget);
  $("validGaugeLabel").textContent = `目标 ${metrics.validTarget.toLocaleString()}，达成 ${Math.min(100, Math.round((metrics.validCount / metrics.validTarget) * 100))}%`;
  $("pendingGaugeLabel").textContent = metrics.pendingCount ? `待验证 ${metrics.pendingCount.toLocaleString()} / ${metrics.pendingTarget.toLocaleString()}` : "暂无待验证";
  $("invalidGaugeLabel").textContent = `占比 ${metrics.invalidPercent.toFixed(1)}%`;
  return metrics;
}

function updateDashboardSummary(data, auto, collectorRunning, validatorRunning, botRunning) {
  const database = data.database || {};
  const app = data.app || {};
  const total = Number(database.current_inventory_nodes ?? database.all_nodes ?? database.total_nodes ?? 0);
  const pending = Number(database.pending_nodes ?? database.statuses?.["未验证"] ?? 0);
  const valid = Number(database.valid_nodes || 0);
  const premium = Number(database.premium_nodes || 0);
  const publish = Number(database.publish_nodes || 0);
  const invalid = Number(database.historical_invalid_nodes ?? database.invalid_nodes_total ?? database.invalid_nodes ?? 0);
  const exportLimit = Number($("subscriptionExportLimit")?.value || 30);
  const output = Math.min(exportLimit || 30, publish);
  setText("dashVersion", app.version ? `当前 ${app.version}` : "版本未知");
  setText("dashTotalNodes", total.toLocaleString());
  setText("dashPendingNodes", pending.toLocaleString());
  setText("dashValidNodes", valid.toLocaleString());
  setText("dashPremiumNodes", premium.toLocaleString());
  setText("dashOutputNodes", output.toLocaleString());
  setText("dashInvalidNodes", invalid.toLocaleString());
  setText("dashSummaryText", `当前库存 ${total.toLocaleString()}：待验证 ${pending.toLocaleString()}，有效 ${valid.toLocaleString()}；优质池 ${premium.toLocaleString()}，预计订阅输出 ${output.toLocaleString()}。`);
  setText("dashAutoState", auto.enabled ? "自动控制开启" : "自动控制关闭");
  setText("dashAutoReason", auto.last_reason || "等待状态同步");
  setText("dashCollectorState", collectorRunning ? "采集中" : "采集停止");
  setText("dashCollectorHint", collectorRunning ? (data.tasks?.collector?.progress?.current_repo || "正在采集") : "等待采集指令");
  setText("dashValidatorState", validatorRunning ? "验证中" : "验证停止");
  setText("dashValidatorHint", validatorRunning ? "正在检测节点可用性" : "等待验证指令");
  setText("dashBotState", botRunning ? "BOT 运行中" : "BOT 停止");
  setLight("dashAutoLight", !!auto.enabled);
  setLight("dashCollectorLight", collectorRunning);
  setLight("dashValidatorLight", validatorRunning);
  setLight("dashBotLight", botRunning);
}

function setGroupedPage(button) {
  document.querySelectorAll(".ops-tabs .page-tab").forEach((tab) => tab.classList.remove("active"));
  document.querySelectorAll(".page").forEach((pageElement) => pageElement.classList.remove("active"));
  button.classList.add("active");
  const meta = PAGE_META[button.id] || PAGE_META.navDashboard;
  $("pageTitle").textContent = meta[0];
  $("pageSubtitle").textContent = meta[1];
  const dashboardOnly = button.dataset.dashboard === "1";
  document.querySelectorAll(".dashboard-only").forEach((item) => {
    item.style.display = dashboardOnly ? "" : "none";
  });
  if (dashboardOnly) return;
  (button.dataset.pages || "").split(/\s+/).filter(Boolean).forEach((id) => {
    const pageElement = $(id);
    if (pageElement) pageElement.classList.add("active");
  });
}

function setPipelineStage(id, state, text) {
  const item = $(id);
  if (!item) return;
  item.classList.remove("ok", "running", "warning", "error");
  if (state) item.classList.add(state);
  const label = item.querySelector("strong");
  if (label) label.textContent = text;
}

function updatePipelineStatus(data = {}) {
  const database = data.database || {};
  const tasks = data.tasks || {};
  const auto = data.control || data.auto || {};
  const collectorRunning = !!tasks.collector?.running;
  const validatorRunning = !!tasks.validator?.running;
  const botRunning = !!tasks.bot?.running;
  const acceptanceRunning = !!tasks.acceptance?.running;
  const repoCount = Number(data.repos?.count || 0);
  const valid = Number(database.valid_nodes || 0);
  const pending = Number(database.pending_nodes || 0);
  const low = Number(auto.config?.valid_low_watermark || 0);
  setPipelineStage("stageCollect", collectorRunning ? "running" : repoCount ? "ok" : "warning", collectorRunning ? "采集中" : repoCount ? `${repoCount} 个源` : "未配置");
  setPipelineStage("stagePool", pending ? "warning" : "ok", pending ? `${pending} 待验证` : "无待验证");
  setPipelineStage("stageValidate", validatorRunning ? "running" : "ok", validatorRunning ? "验证中" : "待命");
  setPipelineStage("stageValid", valid < low ? "warning" : "ok", `${valid} / ${low || 0}`);
  setPipelineStage("stageClaim", "ok", "版本受控");
  setPipelineStage("stageBot", botRunning ? "running" : "warning", botRunning ? "运行中" : "未运行");
  setPipelineStage("stageAcceptance", acceptanceRunning ? "running" : "ok", acceptanceRunning ? "验收中" : "待命");
}

function phaseText(phase) {
  return {
    idle: "空闲",
    collecting: "采集中",
    validating: "验证中",
    rechecking: "复检中",
    stopping: "停止中",
    stopping_collector: "停止采集",
    stopping_validator: "停止验证",
    error: "异常",
  }[phase] || phase || "未知";
}

function modeText(mode) {
  return {
    idle: "空闲",
    auto: "自动运行",
    manual: "手动操作",
    stopping: "停止中",
    collect: "采集",
    validate: "验证",
  }[mode] || mode || "未知";
}

function intentText(intent) {
  return {
    none: "无",
    maintain_pool: "维护节点池",
    collect: "采集节点",
    validate_pending: "验证库存",
    recheck_valid: "复检有效节点",
    collect_to_fill_pool: "采集补齐",
    recover_conflict: "恢复冲突",
    stop_all: "停止全部",
    stop_collector: "停止采集",
    stop_validator: "停止验证",
  }[intent] || intent || "无";
}

function decisionText(decision) {
  return {
    idle: "等待",
    checking: "检查中",
    disabled: "已关闭",
    start_collector: "启动采集",
    start_validator: "启动验证",
    start_valid_recheck: "启动复检",
    stop_validator_conflict: "停止冲突验证",
    stop_collector: "停止采集",
    stop_validator: "停止验证",
    stop_requested: "请求停止",
    worker_finished: "任务结束",
  }[decision] || decision || "等待";
}

function databaseCounts(database = {}) {
  return {
    all: Number(database.all_nodes ?? database.total_nodes ?? 0),
    valid: Number(database.valid_nodes ?? 0),
    pending: Number(database.pending_nodes ?? database.statuses?.["未验证"] ?? 0),
    invalid: Number(database.invalid_nodes ?? database.statuses?.["无效"] ?? 0),
  };
}

function formatDelta(value) {
  if (value > 0) return `+${value}`;
  if (value < 0) return `${value}`;
  return "0";
}

function recentDateKeys(days = 7) {
  const keys = [];
  const now = new Date();
  for (let index = days - 1; index >= 0; index -= 1) {
    const date = new Date(now);
    date.setDate(now.getDate() - index);
    keys.push(date.toISOString().slice(0, 10));
  }
  return keys;
}

function metricValue(rows, date, matcher) {
  return rows
    .filter((item) => item.stat_date === date && matcher(item))
    .reduce((total, item) => total + Number(item.count || 0), 0);
}

function sumValues(values = []) {
  return values.reduce((total, value) => total + Number(value || 0), 0);
}

function buildSeries(rows, dates, definitions) {
  return definitions.map((definition) => ({
    ...definition,
    values: dates.map((date) => metricValue(rows, date, definition.match)),
  }));
}

function buildOpsTrendCharts(rows = [], days = 7) {
  const dates = recentDateKeys(days);
  const charts = [
    {
      id: "claim",
      title: "\u53e3\u4ee4\u9886\u53d6",
      hint: "\u6210\u529f\u3001\u9519\u8bef\u3001\u8fc7\u671f\u548c\u8d85\u9650",
      mode: "stacked",
      series: buildSeries(rows, dates, [
        { id: "success", label: "\u6210\u529f", color: "#188a4f", match: (item) => item.category === "claim" && item.name === "success" },
        { id: "failed", label: "\u9519\u8bef", color: "#c2414b", match: (item) => item.category === "claim" && ["failed", "wrong", "error"].includes(String(item.name || "")) },
        { id: "expired", label: "\u8fc7\u671f", color: "#b7791f", match: (item) => item.category === "claim" && String(item.name || "") === "expired" },
        { id: "limited", label: "\u8d85\u9650", color: "#2563eb", match: (item) => item.category === "claim" && ["limited", "over_limit"].includes(String(item.name || "")) },
      ]),
    },
    {
      id: "access",
      title: "\u8ba2\u9605\u8bbf\u95ee",
      hint: "\u8bbf\u95ee\u6210\u529f\u4e0e\u5931\u8d25",
      mode: "stacked",
      series: buildSeries(rows, dates, [
        { id: "success", label: "\u6210\u529f", color: "#2563eb", match: (item) => item.category === "subscription_access" && item.name === "success" },
        { id: "failed", label: "\u5931\u8d25", color: "#c2414b", match: (item) => item.category === "subscription_access" && item.name !== "success" },
      ]),
    },
    {
      id: "converter",
      title: "\u8ba2\u9605\u8f6c\u6362",
      hint: "\u8f6c\u6362\u6210\u529f\u548c\u5931\u8d25",
      mode: "stacked",
      series: buildSeries(rows, dates, [
        { id: "success", label: "\u6210\u529f", color: "#0f9f8f", match: (item) => item.category === "converter" && String(item.name || "").endsWith(":success") },
        { id: "failed", label: "\u5931\u8d25", color: "#c2414b", match: (item) => item.category === "converter" && !String(item.name || "").endsWith(":success") },
      ]),
    },
    {
      id: "nodes",
      title: "\u8282\u70b9\u6c60",
      hint: "\u539f\u59cb\u3001\u6709\u6548\u548c\u65e0\u6548\u5e93\u5b58",
      mode: "grouped",
      series: buildSeries(rows, dates, [
        { id: "raw", label: "\u539f\u59cb", color: "#607086", match: (item) => item.category === "snapshot" && item.name === "nodes:raw" },
        { id: "valid", label: "\u6709\u6548", color: "#188a4f", match: (item) => item.category === "snapshot" && item.name === "nodes:valid" },
        { id: "invalid", label: "\u65e0\u6548", color: "#b7791f", match: (item) => item.category === "snapshot" && item.name === "nodes:invalid" },
      ]),
    },
  ];
  return { dates, charts };
}

function renderBarChartSvg(dates, chart) {
  const width = 430;
  const height = 210;
  const left = 38;
  const right = 12;
  const top = 14;
  const bottom = 34;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const series = chart.series || [];
  const dayTotals = dates.map((_, index) => {
    if (chart.mode === "stacked") {
      return sumValues(series.map((item) => item.values[index]));
    }
    return Math.max(0, ...series.map((item) => Number(item.values[index] || 0)));
  });
  const maxValue = Math.max(1, ...dayTotals);
  const y = (value) => top + chartHeight - (chartHeight * Number(value || 0)) / maxValue;
  const slot = chartWidth / Math.max(1, dates.length);
  const barArea = Math.max(18, slot * 0.68);
  const grid = [0, 0.5, 1].map((ratio) => {
    const gy = top + chartHeight * ratio;
    const value = Math.round(maxValue * (1 - ratio));
    return `<line x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}" class="trend-grid"></line><text x="6" y="${gy + 4}" class="trend-axis">${value}</text>`;
  }).join("");
  const bars = dates.map((date, dateIndex) => {
    const baseX = left + dateIndex * slot + (slot - barArea) / 2;
    if (chart.mode === "stacked") {
      let currentY = top + chartHeight;
      return series.map((item) => {
        const value = Number(item.values[dateIndex] || 0);
        const barHeight = Math.max(0, currentY - y(value));
        currentY -= barHeight;
        return `<rect x="${baseX}" y="${currentY}" width="${barArea}" height="${barHeight}" rx="3" fill="${item.color}"><title>${chart.title} ${date} ${item.label}: ${value}</title></rect>`;
      }).join("");
    }
    const gap = 3;
    const singleWidth = Math.max(4, (barArea - gap * (series.length - 1)) / Math.max(1, series.length));
    return series.map((item, index) => {
      const value = Number(item.values[dateIndex] || 0);
      const barY = y(value);
      const barHeight = top + chartHeight - barY;
      const x = baseX + index * (singleWidth + gap);
      return `<rect x="${x}" y="${barY}" width="${singleWidth}" height="${barHeight}" rx="3" fill="${item.color}"><title>${chart.title} ${date} ${item.label}: ${value}</title></rect>`;
    }).join("");
  }).join("");
  const xLabels = dates.map((date, index) => {
    const x = left + index * slot + slot / 2;
    return `<text x="${x}" y="${height - 12}" class="trend-axis" text-anchor="middle">${date.slice(5)}</text>`;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(chart.title)}">
      ${grid}
      ${bars}
      ${xLabels}
    </svg>
  `;
}

function renderOpsTrend(data = {}) {
  const days = Number(data.days || 7);
  const rows = data.rows || [];
  const { dates, charts } = buildOpsTrendCharts(rows, days);
  $("opsTrendSummary").innerHTML = charts.map((chart) => {
    const total = sumValues((chart.series || []).flatMap((item) => item.values));
    return `
    <article class="trend-stat">
      <span>${escapeHtml(chart.title)}</span>
      <strong>${Number(total || 0).toLocaleString()}</strong>
    </article>
  `}).join("");
  $("opsTrendChart").innerHTML = charts.map((chart) => `
    <article class="trend-card">
      <div class="trend-card-head">
        <div>
          <strong>${escapeHtml(chart.title)}</strong>
          <span>${escapeHtml(chart.hint)}</span>
        </div>
        <div class="trend-legend">
          ${(chart.series || []).map((item) => `<span><i style="background:${item.color}"></i>${escapeHtml(item.label)}</span>`).join("")}
        </div>
      </div>
      ${renderBarChartSvg(dates, chart)}
    </article>
  `).join("");
}

async function refreshOpsStats() {
  try {
    const data = await jsonFetch(api("/api/ops-stats?days=7"));
    renderOpsTrend(data);
  } catch (error) {
    $("opsTrendChart").innerHTML = `<p class="hint">${escapeHtml(error.message)}</p>`;
  }
}

function updateNodeFlowStatus(database, collectorRunning, validatorRunning, auto = {}) {
  const current = databaseCounts(database);
  let message = "验证会把节点从“未验证”流转到“有效/无效”，节点总数只在采集入库时变化。";
  if (lastDatabaseSnapshot) {
    const delta = {
      all: current.all - lastDatabaseSnapshot.all,
      valid: current.valid - lastDatabaseSnapshot.valid,
      pending: current.pending - lastDatabaseSnapshot.pending,
      invalid: current.invalid - lastDatabaseSnapshot.invalid,
    };
    if (delta.all || delta.valid || delta.pending || delta.invalid) {
      message = `本次流转：总数 ${formatDelta(delta.all)}，未验证 ${formatDelta(delta.pending)}，有效 ${formatDelta(delta.valid)}，无效 ${formatDelta(delta.invalid)}。`;
    }
  }
  if (validatorRunning) {
    message += " 当前正在验证，未验证会逐步下降，有效或无效会逐步上升。";
  } else if (collectorRunning) {
    message += " 当前正在采集，采集入库后节点总数和未验证库存会增加。";
  } else if (auto.phase && auto.phase !== "idle") {
    message += ` 当前总控阶段：${phaseText(auto.phase)}。`;
  }
  $("nodeFlowStatus").textContent = message;
  lastDatabaseSnapshot = current;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setStepState(id, state) {
  const el = $(id);
  if (!el) return;
  el.classList.remove("active", "done");
  if (state) el.classList.add(state);
}

function updateModuleDashboards(data, collectorRunning, validatorRunning, auto = {}) {
  const database = data.database || {};
  const current = databaseCounts(database);
  const now = Date.now();
  const elapsedMinutes = Math.max((now - moduleSnapshotAt) / 60000, 1 / 60);
  const delta = moduleSnapshot ? {
    all: current.all - moduleSnapshot.all,
    valid: current.valid - moduleSnapshot.valid,
    pending: current.pending - moduleSnapshot.pending,
    invalid: current.invalid - moduleSnapshot.invalid,
  } : { all: 0, valid: 0, pending: 0, invalid: 0 };
  const progress = data.tasks?.collector?.progress || {};
  const inserted = Number(progress.inserted_nodes || 0);
  const parsed = Number(progress.parsed_nodes || 0);
  const duplicates = Number(progress.duplicate_nodes || 0);
  const requests = Number(progress.fetched_files || 0) + Number(progress.directory_pages || 0);
  const failed = Number(progress.failed_requests || 0);
  const rate = Math.max(0, Math.round(Math.max(delta.all, inserted) / elapsedMinutes));
  const lowWatermark = Number(auto.config?.valid_low_watermark || 1000);
  const watermarkPercent = lowWatermark ? Math.min(999, Math.round((current.valid / lowWatermark) * 100)) : 100;
  const validateCurrent = Number(auto.validate?.current || Math.max(0, delta.valid));
  const validateTarget = Number(auto.validate?.target || 0);

  setText("collectMetricState", collectorRunning ? "采集中" : "已停止");
  setText("collectMetricReason", collectorRunning ? (progress.current_repo || "正在读取采集进度") : (auto.last_reason || "等待采集指令"));
  setText("collectMetricAll", current.all.toLocaleString());
  setText("collectMetricDelta", `本轮变化 ${formatDelta(delta.all)}`);
  setText("collectMetricInserted", inserted.toLocaleString());
  setText("collectMetricDuplicate", `重复 ${duplicates.toLocaleString()}`);
  setText("collectMetricRate", `${rate}/分`);
  setText("collectMetricRequests", `请求 ${requests.toLocaleString()} / 失败 ${failed.toLocaleString()}`);
  setStepState("collectStepScan", collectorRunning ? "active" : (requests ? "done" : ""));
  setStepState("collectStepParse", parsed ? (collectorRunning ? "active" : "done") : "");
  setStepState("collectStepFilter", duplicates ? (collectorRunning ? "active" : "done") : "");
  setStepState("collectStepStore", inserted ? "done" : "");

  setText("validateMetricState", validatorRunning ? "验证中" : "已停止");
  setText("validateMetricReason", validatorRunning ? (validateTarget ? `本轮有效 ${validateCurrent}/${validateTarget}` : "正在验证节点质量") : (auto.last_reason || "等待验证指令"));
  setText("validateMetricPending", current.pending.toLocaleString());
  setText("validateMetricPendingDelta", `变化 ${formatDelta(delta.pending)}`);
  setText("validateMetricValid", current.valid.toLocaleString());
  setText("validateMetricValidDelta", `新增 ${formatDelta(delta.valid)}`);
  setText("validateMetricWatermark", `${watermarkPercent}%`);
  setText("validateMetricWatermarkText", `阈值 ${lowWatermark.toLocaleString()}`);
  setText("funnelPending", current.pending.toLocaleString());
  setText("funnelValid", current.valid.toLocaleString());
  setText("funnelPremium", Number(database.premium_nodes || 0).toLocaleString());
  setText("funnelInvalid", Number(database.invalid_nodes_total || database.invalid_nodes || 0).toLocaleString());

  setText("subscriptionMetricValid", current.valid.toLocaleString());
  setText("subscriptionMetricPremium", `优质池 ${Number(database.premium_nodes || 0).toLocaleString()}`);
  setText("subscriptionMetricPublish", Number(database.publish_nodes || 0).toLocaleString());

  moduleSnapshot = current;
  moduleSnapshotAt = now;
}

function applyAutoConfig(config = {}) {
  $("autoValidLow").value = config.valid_low_watermark ?? 1000;
  $("autoCollectTarget").value = config.collect_insert_target ?? 20000;
  $("autoValidateTarget").value = config.validate_valid_target ?? 200;
  $("autoCheckIntervalMinutes").value = config.check_interval_minutes ?? 5;
  $("autoCollectorWorkers").value = config.collector_workers ?? 5;
  $("autoCollectorDepth").value = config.collector_depth ?? 8;
  $("autoCollectorDelay").value = config.collector_delay ?? 1;
  $("autoCollectorJitter").value = config.collector_jitter ?? 0.5;
  $("autoCollectorLogLevel").value = config.collector_log_level || "detail";
  $("autoValidatorWorkers").value = config.validator_workers ?? 20;
  $("autoValidatorRounds").value = config.validator_rounds ?? 1;
  $("autoValidatorTimeout").value = config.validator_timeout ?? 5;
  $("autoRecheckEnabled").checked = !!config.recheck_enabled;
  $("autoRecheckIntervalMinutes").value = config.recheck_interval_minutes ?? 360;
  $("autoRecheckLimit").value = config.recheck_limit ?? 50;
}

function autoPayload() {
  return {
    valid_low_watermark: $("autoValidLow").value,
    collect_insert_target: $("autoCollectTarget").value,
    validate_valid_target: $("autoValidateTarget").value,
    check_interval_minutes: $("autoCheckIntervalMinutes").value,
    collector_workers: $("autoCollectorWorkers").value,
    collector_depth: $("autoCollectorDepth").value,
    collector_delay: $("autoCollectorDelay").value,
    collector_jitter: $("autoCollectorJitter").value,
    collector_log_level: $("autoCollectorLogLevel").value,
    validator_workers: $("autoValidatorWorkers").value,
    validator_rounds: $("autoValidatorRounds").value,
    validator_timeout: $("autoValidatorTimeout").value,
    recheck_enabled: $("autoRecheckEnabled").checked,
    recheck_interval_minutes: $("autoRecheckIntervalMinutes").value,
    recheck_limit: $("autoRecheckLimit").value,
  };
}

async function saveAutoConfig() {
  const data = await jsonFetch(api("/api/auto/config"), { method: "POST", body: JSON.stringify(autoPayload()) });
  applyAutoConfig(data.config || data.auto?.config);
  await refreshStatus();
  toast("自动控制参数已保存");
}

async function refreshStatus() {
  try {
    const data = await jsonFetch(api("/api/status"));
    if (data.app?.version) {
      $("pageTitle").textContent = `${APP_TITLE_PREFIX} ${data.app.version}`;
      document.title = `${APP_TITLE_PREFIX} ${data.app.version}`;
    }
    $("connectionDot").classList.add("online");
    $("connectionText").textContent = "本地服务在线";
    $("totalNodes").textContent = data.database.current_inventory_nodes ?? data.database.all_nodes ?? data.database.total_nodes;
    $("validNodes").textContent = data.database.valid_nodes;
    $("pendingNodes").textContent = data.database.pending_nodes ?? (data.database.statuses["未验证"] || 0);
    $("invalidNodes").textContent = data.database.invalid_nodes ?? (data.database.statuses["无效"] || 0);
    $("duplicateNodes").textContent = data.database.duplicate_filtered || 0;
    $("repoCount").textContent = `${data.repos?.count || 0} 个仓库`;
    const collectorRunning = data.tasks.collector.running;
    const validatorRunning = data.tasks.validator.running;
    const botRunning = data.tasks.bot?.running || false;
    updateDashboardSummary(data, data.control || data.auto || {}, collectorRunning, validatorRunning, botRunning);
    taskBadge("collectorBadge", collectorRunning);
    taskBadge("validatorBadge", validatorRunning);
    taskBadge("botBadge", botRunning);
    $("startCollector").disabled = collectorRunning || validatorRunning;
    $("stopCollector").disabled = !data.tasks.collector.running;
    $("startValidator").disabled = validatorRunning || collectorRunning;
    $("stopValidator").disabled = !data.tasks.validator.running;
    setButtonLight("startCollector", collectorRunning ? "running" : (validatorRunning ? "warning" : "ok"));
    setButtonLight("stopCollector", collectorRunning ? "error" : "off");
    setButtonLight("clearPendingNodes", collectorRunning || validatorRunning ? "warning" : "ok");
    setButtonLight("clearValidNodes", collectorRunning || validatorRunning ? "warning" : "error");
    setButtonLight("startValidator", validatorRunning ? "running" : (collectorRunning ? "warning" : "ok"));
    setButtonLight("recheckValidNodes", validatorRunning ? "running" : "ok");
    setButtonLight("stopValidator", validatorRunning ? "error" : "off");
    const auto = data.control || data.auto || {};
    updateCockpit(data, auto, collectorRunning, validatorRunning);
    updateNodeFlowStatus(data.database, collectorRunning, validatorRunning, auto);
    updateModuleDashboards(data, collectorRunning, validatorRunning, auto);
    updatePipelineStatus(data);
    renderManualImportLogs(data.manual_import_logs || []);
    $("autoBadge").textContent = auto.enabled ? "已开启" : "已关闭";
    $("autoBadge").classList.toggle("running", !!auto.enabled);
    $("autoPhase").textContent = phaseText(auto.phase);
    $("autoReason").textContent = auto.last_reason || "等待状态同步";
    $("controlMode").textContent = modeText(auto.mode);
    $("controlIntent").textContent = intentText(auto.intent);
    $("controlDecision").textContent = decisionText(auto.decision);
    $("autoNotice").textContent = autoNoticeText(auto, data.database);
    $("autoValidCount").textContent = data.database.valid_nodes;
    $("autoLowWatermarkView").textContent = auto.config?.valid_low_watermark ?? 0;
    $("autoPendingCount").textContent = data.database.pending_nodes ?? data.database.total_nodes;
    $("autoCollectProgress").textContent = `${auto.collect?.current ?? 0} / ${auto.collect?.target ?? 0}`;
    $("autoValidateProgress").textContent = `${auto.validate?.current ?? 0} / ${auto.validate?.target ?? 0}`;
    $("autoCollectorState").textContent = collectorRunning ? "采集运行中" : "采集已停止";
    $("autoValidatorState").textContent = validatorRunning ? "验证运行中" : "验证已停止";
    setLight("autoLight", !!auto.enabled, auto.phase === "error");
    setLight("autoCollectorLight", collectorRunning);
    setLight("autoValidatorLight", validatorRunning);
    $("startAuto").disabled = !!auto.enabled;
    $("stopAuto").disabled = !auto.enabled && !collectorRunning && !validatorRunning;
    setButtonLight("startAuto", auto.enabled ? "running" : "ok");
    setButtonLight("stopAuto", auto.enabled || collectorRunning || validatorRunning ? "warning" : "off");
    setButtonLight("navDashboard", auto.enabled ? "running" : "ok");
    setButtonLight("navCollect", collectorRunning ? "running" : "ok");
    setButtonLight("navValidate", validatorRunning ? "running" : "ok");
    setButtonLight("navNodes", data.database.valid_nodes ? "ok" : "warning");
    setButtonLight("navBot", botRunning ? "running" : "ok");
    if (!refreshStatus.autoConfigLoaded) {
      applyAutoConfig(auto.config || {});
      refreshStatus.autoConfigLoaded = true;
    }
    const progress = data.tasks.collector.progress || {};
    $("collectorRepo").textContent = progress.current_repo || "-";
    $("collectorUrl").textContent = progress.current_url || "-";
    $("collectorActive").textContent = progress.active_requests || 0;
    $("collectorPages").textContent = progress.directory_pages || 0;
    $("collectorCandidates").textContent = progress.candidate_files || 0;
    $("collectorFetched").textContent = progress.fetched_files || 0;
    $("collectorNoNodeFiles").textContent = progress.no_node_files || 0;
    $("collectorFailed").textContent = progress.failed_requests || 0;
    $("collectorParsed").textContent = progress.parsed_nodes || 0;
    $("collectorInserted").textContent = progress.inserted_nodes || 0;
    $("collectorDuplicates").textContent = progress.duplicate_nodes || 0;
  } catch (error) {
    $("connectionDot").classList.remove("online");
    $("connectionText").textContent = "连接已断开";
  }
}

function applyBotConfig(config = {}) {
  $("botToken").value = config.bot_token || "";
  $("botUsername").value = config.bot_username || "";
  $("botAutoRun").checked = !!config.auto_run;
  $("botKeywords").value = config.keywords || "";
  $("botGroupPromptMessage").value = config.group_prompt_message || "";
  $("botPrivateInstructionMessage").value = config.private_instruction_message || "";
  $("botSubscriptionCardMessage").value = config.subscription_card_message || "";
  $("botPublicBaseUrl").value = config.public_base_url || "";
  $("botYoutubeChannelUrl").value = config.youtube_channel_url || config.youtube_url || "";
  $("botLatestVideoUrl").value = config.latest_free_node_video_url || "";
  $("botYoutubeGuideMessage").value = config.youtube_guide_message || "";
  $("botSubscriptionMaxUses").value = config.subscription_max_uses ?? 10;
  $("botSubscriptionExpireHours").value = config.subscription_expire_hours ?? 24;
  $("botSubscriptionExportLimit").value = config.subscription_export_limit ?? 20;
  setText("botClaimEntryState", config.claim_entry_ok ? "群按钮直达私聊" : "群按钮入口未配置");
  setText("botClaimEntryUrl", config.bot_private_start_url || config.claim_entry_reason || "请填写机器人用户名");
  setLight("botClaimEntryLight", !!config.claim_entry_ok, !config.claim_entry_ok);
}

function botPayload() {
  return {
    bot_token: $("botToken").value,
    bot_username: $("botUsername").value,
    auto_run: $("botAutoRun").checked,
    keywords: $("botKeywords").value,
    group_prompt_message: $("botGroupPromptMessage").value,
    private_instruction_message: $("botPrivateInstructionMessage").value,
    subscription_card_message: $("botSubscriptionCardMessage").value,
    public_base_url: $("botPublicBaseUrl").value,
    youtube_channel_url: $("botYoutubeChannelUrl").value,
    latest_free_node_video_url: $("botLatestVideoUrl").value,
    youtube_guide_message: $("botYoutubeGuideMessage").value,
    subscription_max_uses: $("botSubscriptionMaxUses").value,
    subscription_expire_hours: $("botSubscriptionExpireHours").value,
    subscription_export_limit: $("botSubscriptionExportLimit").value,
  };
}

function applyClaimCodeConfig(config = {}) {
  $("claimCodeEnabled").checked = config.enabled !== false;
  $("claimCodeValue").value = config.code || "";
  $("claimCodeVersion").value = config.version || "v1";
  $("claimCodeDailyLimit").value = config.daily_limit ?? 1;
  $("claimCodeExpiresAt").value = (config.expires_at || "").replace(" ", "T").slice(0, 16);
  $("claimSuccessMessage").value = config.success_message || "";
  $("claimWrongCodeMessage").value = config.wrong_code_message || "";
  $("claimExpiredMessage").value = config.expired_message || "";
  $("claimLimitExceededMessage").value = config.limit_exceeded_message || "";
  $("claimTestVersion").value = config.version || "v1";
  $("claimCodeBadge").textContent = config.enabled === false ? "已关闭" : `版本 ${config.version || "v1"}`;
  $("claimCodeBadge").classList.toggle("running", config.enabled !== false);
  $("claimCodeNotice").textContent = `当前版本 ${config.version || "v1"}，每日每个客户端最多成功领取 ${config.daily_limit ?? 1} 次。口令有效期只限制领取和验证码；更换版本后旧订阅链接无法导出真实节点。`;
  setText("subscriptionMetricClaimVersion", config.version || "v1");
  setPipelineStage("stageClaim", config.enabled === false ? "warning" : "ok", config.enabled === false ? "已关闭" : `版本 ${config.version || "v1"}`);
}

function claimCodePayload() {
  return {
    enabled: $("claimCodeEnabled").checked,
    code: $("claimCodeValue").value,
    version: $("claimCodeVersion").value,
    expires_at: $("claimCodeExpiresAt").value,
    daily_limit: $("claimCodeDailyLimit").value,
    success_message: $("claimSuccessMessage").value,
    wrong_code_message: $("claimWrongCodeMessage").value,
    expired_message: $("claimExpiredMessage").value,
    limit_exceeded_message: $("claimLimitExceededMessage").value,
  };
}

async function refreshClaimCodeConfig() {
  try {
    const data = await jsonFetch(api("/api/claim-code/config"));
    applyClaimCodeConfig(data.config || {});
  } catch (error) {
    toast(error.message);
  }
}

async function saveClaimCodeConfig() {
  try {
    const data = await jsonFetch(api("/api/claim-code/config"), {
      method: "POST",
      body: JSON.stringify(claimCodePayload()),
    });
    applyClaimCodeConfig(data.config || {});
    toast("领取口令配置已保存");
  } catch (error) {
    toast(error.message);
  }
}

async function testClaimCode() {
  try {
    const data = await jsonFetch("/api/claim-code/redeem", {
      method: "POST",
      body: JSON.stringify({
        code: $("claimTestCode").value,
        version: $("claimTestVersion").value,
        client_id: $("claimTestClient").value,
      }),
    });
    $("claimTestResult").textContent = `${data.status || "success"}：${data.message || ""}`;
    toast(data.message || "领取成功");
  } catch (error) {
    $("claimTestResult").textContent = error.message;
    toast(error.message);
  }
}

async function refreshBot() {
  try {
    const data = await jsonFetch(api("/api/bot"));
    applyBotConfig(data.config || {});
    taskBadge("botBadge", data.task?.running || false);
    $("botState").textContent = data.state || "未知";
    $("botAutoState").textContent = data.auto_run ? "自动运行已开启" : "自动运行已关闭";
    setLight("botStateLight", !!data.task?.running, data.state === "配置不完整");
    setLight("botAutoLight", !!data.auto_run);
    $("startBot").disabled = !!data.task?.running;
    $("stopBot").disabled = !data.task?.running;
    $("disableBot").disabled = !data.auto_run && !data.task?.running;
    setPipelineStage("stageBot", data.task?.running ? "running" : data.state === "配置不完整" ? "warning" : "ok", data.task?.running ? "运行中" : data.state || "待命");
    renderBotMessages(data.messages || []);
  } catch (error) {
    toast(error.message);
  }
}

function renderBotMessages(messages = []) {
  $("botMessages").innerHTML = messages.length ? messages.map((item) => `
    <article class="profile-card">
      <div class="node-meta"><span class="protocol">${escapeHtml(item.direction)}</span><span>${escapeHtml(item.created_at || "")}</span><span>用户 ${escapeHtml(item.telegram_user_id || "未知")}</span></div>
      <div class="node-uri">${escapeHtml(item.message || "")}</div>
    </article>`).join("") : `<p class="hint">暂无 BOT 消息记录。</p>`;
}

async function saveBotConfig() {
  try {
    const data = await jsonFetch(api("/api/bot/config"), { method: "POST", body: JSON.stringify(botPayload()) });
    applyBotConfig(data.config || {});
    toast("BOT 配置已保存");
  } catch (error) {
    toast(error.message);
  }
}

function botSimulationPayload() {
  return {
    chat_type: $("botSimChatType").value,
    text: $("botSimText").value,
    user_id: $("botSimUserId").value,
    chat_id: $("botSimChatId").value,
    username: $("botSimUsername").value,
  };
}

async function runBotSimulation() {
  try {
    const data = await jsonFetch(api("/api/bot/simulate"), {
      method: "POST",
      body: JSON.stringify(botSimulationPayload()),
    });
    const result = data.result || {};
    const subscription = result.subscription || {};
    const replyCount = (result.replies || []).length;
    const hasButton = (result.replies || []).some((reply) => !!reply.reply_markup);
    $("botSimResult").textContent = `动作：${result.action || "-"}；状态：${result.status || "-"}；关键词：${result.matched_keyword ? "命中" : "未命中"}；回复 ${replyCount} 条；按钮：${hasButton ? "已生成" : "无"}；订阅：${result.subscription_created ? subscription.token || "已生成" : "未生成"}`;
    if (data.messages) {
      renderBotMessages(data.messages);
    }
    toast("BOT 模拟验证完成");
  } catch (error) {
    $("botSimResult").textContent = error.message;
    toast(error.message);
  }
}

async function runBotFlowSimulation() {
  try {
    const data = await jsonFetch(api("/api/bot/simulate-flow"), {
      method: "POST",
      body: JSON.stringify({
        user_id: $("botSimUserId").value,
        username: $("botSimUsername").value,
        group_chat_id: $("botSimChatId").value,
      }),
    });
    $("botSimResult").textContent = `完整流程：${data.ok ? "通过" : "失败"}；用户 ${data.user_id || "-"}；关键词 ${data.keyword || "-"}；口令版本 ${data.claim_version || "-"}；测试订阅 ${data.cleanup_deleted ? "已清理" : "未清理"}`;
    renderBotFlowSteps(data.steps || []);
    if (data.messages) renderBotMessages(data.messages);
    toast(data.ok ? "BOT 完整流程通过" : "BOT 完整流程存在失败步骤");
  } catch (error) {
    $("botSimResult").textContent = error.message;
    $("botFlowSteps").innerHTML = "";
    toast(error.message);
  }
}

function renderBotFlowSteps(steps = []) {
  $("botFlowSteps").innerHTML = steps.length ? steps.map((step, index) => `
    <article class="profile-card ${step.ok ? "success" : "failed"}">
      <div class="node-meta"><span class="protocol">${step.ok ? "通过" : "失败"}</span><span>步骤 ${index + 1}</span><span>${escapeHtml(step.name || "")}</span></div>
      <div class="node-uri">${escapeHtml(step.detail || "")}</div>
    </article>
  `).join("") : "";
}

function syncBotSimulationChatDefaults() {
  const isPrivate = $("botSimChatType").value === "private";
  $("botSimChatId").value = isPrivate ? ($("botSimUserId").value || "200001") : "-100001";
}

async function refreshRepos() {
  try {
    const data = await jsonFetch(api("/api/repos"));
    $("repoList").value = (data.items || []).map((item) => item.repo).join("\n");
    $("repoCount").textContent = `${data.count || 0} / ${data.total || data.count || 0} 个启用`;
    renderRepoItems(data.items || []);
  } catch (error) {
    toast(error.message);
  }
}

function renderRepoItems(items) {
  $("repoItems").innerHTML = items.length ? items.map((item) => `
    <article class="profile-card">
      <div class="node-meta">
        <span class="protocol">${item.enabled ? "启用" : "禁用"}</span>
        <span>排序 ${item.sort_order ?? 0}</span>
        <span>更新 ${escapeHtml(item.updated_at || "默认配置")}</span>
      </div>
      <div class="node-uri">${escapeHtml(item.repo || "")}</div>
      <div class="actions compact-actions">
        <button class="ghost" data-toggle-repo="${escapeHtml(item.repo || "")}" data-enabled="${item.enabled ? "0" : "1"}">${item.enabled ? "禁用仓库" : "启用仓库"}</button>
      </div>
    </article>
  `).join("") : `<p class="hint">暂无采集仓库。请先保存仓库画像或恢复默认仓库。</p>`;
  bindRepoActions();
}

function bindRepoActions() {
  document.querySelectorAll("[data-toggle-repo]").forEach((button) => {
    button.onclick = async () => {
      const repo = encodeURIComponent(button.dataset.toggleRepo || "");
      const action = button.dataset.enabled === "1" ? "enable" : "disable";
      await post(api(`/api/repos/${repo}/${action}`));
      await refreshRepos();
    };
  });
}

async function refreshProfiles() {
  try {
    const data = await jsonFetch(api("/api/source-profiles?limit=30"));
    $("sourceProfiles").innerHTML = (data.profiles || []).length ? data.profiles.map((item) => `
      <article class="profile-card">
        <div class="node-meta"><span class="protocol">${escapeHtml(item.repo)}</span><span>累计节点 ${item.node_count}</span><span>成功 ${item.success_count}</span><span>失败 ${item.fail_count}</span></div>
        <div class="node-uri">${escapeHtml(item.source)}</div>
      </article>`).join("") : `<p class="hint">暂无来源画像。采集成功后会自动记录到数据库。</p>`;
  } catch (error) {
    toast(error.message);
  }
}

async function post(url, payload = {}) {
  try {
    const data = await jsonFetch(url, { method: "POST", body: JSON.stringify(payload) });
    await refreshStatus();
    return data;
  } catch (error) {
    toast(error.message);
    return null;
  }
}

async function clearNodePool(scope) {
  const label = scope === "valid" ? "清空有效节点" : "清空未验证节点";
  const warning = scope === "valid"
    ? "这会删除有效节点库和订阅候选池，正在运行的订阅可能拿不到真实节点。"
    : "这会删除未验证节点池，后续需要重新采集补充。";
  const confirmText = prompt(`${warning}\n如确认执行，请输入：${label}`);
  if (confirmText !== label) {
    toast("已取消清理");
    return;
  }
  try {
    const data = await jsonFetch(api("/api/nodes/clear"), {
      method: "POST",
      body: JSON.stringify({ scope, confirm: label }),
    });
    toast(`${label}完成`);
    await refreshStatus();
    await refreshNodes();
    return data;
  } catch (error) {
    toast(error.message);
  }
}

function renderLogs() {
  const visible = logEvents.filter((event) => logFilter === "all" || event.source === logFilter);
  $("logs").textContent = visible.map((event) => `[${event.time}] [${event.source}] ${event.message}`).join("\n");
  $("logs").scrollTop = $("logs").scrollHeight;
  renderModuleLogs("collectLogs", ["collector"]);
  renderModuleLogs("validateLogs", ["validator"]);
  renderModuleLogs("subscriptionLogs", ["subscription", "converter"]);
}

function renderModuleLogs(targetId, sources) {
  const target = $(targetId);
  if (!target) return;
  const rows = logEvents
    .filter((event) => sources.includes(event.source))
    .slice(-24)
    .map((event) => `[${event.time}] ${event.message}`);
  target.textContent = rows.join("\n") || "暂无日志。";
  target.scrollTop = target.scrollHeight;
}

function connectLogs() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(api("/api/events"));
  eventSource.onmessage = ({ data }) => {
    logEvents.push(JSON.parse(data));
    if (logEvents.length > 800) logEvents.shift();
    renderLogs();
    refreshStatus();
  };
  eventSource.onerror = () => setTimeout(refreshStatus, 1200);
}

function manualImportSourceLabel(value) {
  return {
    raw_uri: "原始URI",
    base64_text: "Base64",
    subscription_url: "订阅URL",
    mixed: "混合输入",
  }[value] || "混合输入";
}

function renderManualImportLogs(items = []) {
  const target = $("manualImportLogs");
  if (!target) return;
  target.innerHTML = items.length ? items.map((item) => `
    <article class="profile-card">
      <div class="node-meta">
        <span class="protocol">${escapeHtml(manualImportSourceLabel(item.input_source_type))}</span>
        <span>${escapeHtml(item.created_at || "-")}</span>
        <span>写入 ${Number(item.added_count || 0)}</span>
        <span>重复 ${Number(item.duplicate_count || 0)}</span>
        <span>失败 ${Number(item.invalid_count || 0)}</span>
      </div>
      <div class="node-meta">
        <span>订阅URL ${Number(item.subscription_url_count || 0)}</span>
        <span>Base64 ${Number(item.base64_decoded_count || 0)}</span>
        <span>提取 ${Number(item.extracted_count || 0)}</span>
        <span>source ${escapeHtml(item.selected_source_type || "-")}</span>
      </div>
      <div class="node-uri">${escapeHtml(item.error_summary || item.manual_note || "无错误摘要")}</div>
    </article>
  `).join("") : `<p class="hint">暂无导入记录。导入原始节点、Base64 或订阅 URL 后会显示在这里。</p>`;
}

async function refreshNodes() {
  try {
    const protocol = encodeURIComponent($("validProtocol").value);
    const country = encodeURIComponent($("validCountry").value);
    const group = encodeURIComponent($("validGroup")?.value || "");
    const data = await jsonFetch(api(`/api/valid-nodes?page=${page}&limit=${nodePageSize}&protocol=${protocol}&country=${country}&group=${group}`));
    nodeTotal = data.total;
    $("pageText").textContent = `第 ${page} 页 · 共 ${nodeTotal} 条`;
    $("previousPage").disabled = page <= 1;
    $("nextPage").disabled = page * data.limit >= nodeTotal;
    updateSelectOptions("validProtocol", data.protocols || [], "全部协议");
    updateSelectOptions("validCountry", data.countries || [], "全部国家");
    $("nodeList").innerHTML = data.nodes.length ? data.nodes.map((node) => {
      const published = !!node.published;
      const disabled = !!node.manual_disabled;
      const classes = ["node-card", "compact-node", published ? "published-node" : "", disabled ? "disabled-node" : ""].filter(Boolean).join(" ");
      return `
      <article class="${classes}">
        <div class="node-meta compact-node-meta">
          <span class="protocol">${escapeHtml(node.protocol || "-")}</span>
          <span>地区 ${escapeHtml(node.country || "未知")}</span>
          <span>${Number(node.seconds || 0).toFixed(2)} 秒</span>
          <span>评分 ${node.quality_score ?? 0}</span>
          <span>${node.source_type === "manual_cf" ? "自建CF" : node.manual_added ? "手动普通" : "GitHub公开"}</span>
          <span>${node.cf_candidate ? "CF 候选" : "普通候选"}</span>
          <span>${published ? "已发布 ✓" : "未发布"}</span>
          <span>${disabled ? "已禁用" : "可管理"}</span>
        </div>
        <div class="node-name">${escapeHtml(node.server || "未知 server")} : ${escapeHtml(node.port || "-")}</div>
        <div class="node-meta compact-node-meta">
          <span>network ${escapeHtml(node.network || "-")}</span>
          <span>TLS ${node.tls ? "yes" : "no"}</span>
          <span>source ${escapeHtml(node.source_type || "-")}</span>
          <span>note ${escapeHtml(node.manual_note || "-")}</span>
          <span>最近 ${escapeHtml(node.last_validated || "-")}</span>
        </div>
        <div class="actions compact-actions">
          <button class="ghost" data-valid-copy="${escapeHtml(node.uri || "")}" ${disabled ? "disabled" : ""}>复制节点</button>
          ${published ? "" : `<button class="primary" data-valid-publish="${escapeHtml(node.uri || "")}" ${disabled ? "disabled" : ""}>标记可发布</button>`}
          ${published ? `<button class="ghost" data-valid-unpublish="${escapeHtml(node.uri || "")}">移出发布池</button>` : ""}
          <button class="ghost" data-valid-premium-remove="${escapeHtml(node.uri || "")}">移出优质池</button>
          <button class="ghost" data-valid-disable="${escapeHtml(node.uri || "")}" ${disabled ? "disabled" : ""}>禁用</button>
          <button class="danger" data-valid-delete="${escapeHtml(node.uri || "")}">删除</button>
        </div>
      </article>`}).join("") : `<p class="hint">暂无有效节点。启动验证后，通过稳定检查的节点会出现在这里，也可以手动导入候选。</p>`;
    bindValidNodeActions();
  } catch (error) {
    toast(error.message);
  }
}

async function importManualNodes() {
  try {
    const data = await jsonFetch(api("/api/valid-nodes/manual-import"), {
      method: "POST",
      body: JSON.stringify({
        nodes: $("manualNodeInput").value,
        note: $("manualNodeNote").value,
        source_type: $("manualNodeSourceType").value,
      }),
    });
    const result = data.result || {};
    setText("manualNodeImportSummary", `新增 ${result.added_count || 0}，重复 ${result.duplicate_count || 0}，无效 ${result.invalid_count || 0}，解析订阅 ${result.subscription_url_count || 0}，Base64 解码 ${result.base64_decoded_count || 0}，提取节点 ${result.extracted_count || 0}`);
    if (result.invalid?.length) {
      toast(`有 ${result.invalid.length} 条格式错误，已拒绝入库`);
    } else {
      toast("手动节点导入完成");
    }
    if (result.added_count) $("manualNodeInput").value = "";
    await refreshStatus();
    await refreshNodes();
    await refreshPublishPool();
  } catch (error) {
    toast(error.message);
  }
}

async function copyTextToClipboard(value) {
  if (!value) {
    toast("没有可复制的节点");
    return false;
  }
  try {
    await navigator.clipboard?.writeText(value);
  } catch (error) {
    const area = document.createElement("textarea");
    area.value = value;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    document.body.removeChild(area);
  }
  return true;
}

async function copyValidNodes(payload) {
  const data = await jsonFetch(api("/api/valid-nodes/copy"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (await copyTextToClipboard(data.content || "")) {
    toast(`已复制 ${data.count || 0} 条节点`);
  }
  return data;
}

async function copyFilteredNodes() {
  await copyValidNodes({
    protocol: $("validProtocol").value,
    country: $("validCountry").value,
    group: $("validGroup").value,
    limit: 500,
  });
}

function bindValidNodeActions() {
  document.querySelectorAll("[data-valid-copy]").forEach((button) => {
    button.onclick = async () => {
      await copyValidNodes({ uri: button.dataset.validCopy || "" });
    };
  });
  document.querySelectorAll("[data-valid-publish]").forEach((button) => {
    button.onclick = async () => {
      const data = await post(api("/api/publish-pool/mark"), { uri: button.dataset.validPublish || "", publishable: true });
      if (data) {
        renderPublishPool(data);
        await refreshNodes();
        toast("已标记为可发布");
      }
    };
  });
  document.querySelectorAll("[data-valid-unpublish]").forEach((button) => {
    button.onclick = async () => {
      const data = await post(api("/api/publish-pool/remove"), { uri: button.dataset.validUnpublish || "" });
      if (data) {
        renderPublishPool(data);
        await refreshNodes();
        toast("已移出发布池");
      }
    };
  });
  document.querySelectorAll("[data-valid-premium-remove]").forEach((button) => {
    button.onclick = async () => {
      await post(api("/api/valid-nodes/remove-premium"), { uri: button.dataset.validPremiumRemove || "" });
      await refreshNodes();
      await refreshPublishPool();
      toast("已移出优质池");
    };
  });
  document.querySelectorAll("[data-valid-disable]").forEach((button) => {
    button.onclick = async () => {
      if (!confirm("确定禁用这个有效节点吗？禁用后会同步移出优质池、发布池并清空转换缓存。")) return;
      await post(api("/api/valid-nodes/disable"), { uri: button.dataset.validDisable || "", reason: "manual_node_disable" });
      await refreshNodes();
      await refreshPublishPool();
      toast("节点已禁用");
    };
  });
  document.querySelectorAll("[data-valid-delete]").forEach((button) => {
    button.onclick = async () => {
      if (!confirm("确定删除这个有效节点吗？删除后会同步移出优质池、发布池并清空转换缓存。")) return;
      await post(api("/api/valid-nodes/delete"), { uri: button.dataset.validDelete || "", reason: "manual_node_delete" });
      await refreshNodes();
      await refreshPublishPool();
      toast("节点已删除");
    };
  });
}

async function refreshProcessingConfig() {
  try {
    const data = await jsonFetch(api("/api/node-processing/config"));
    $("renameTemplate").value = data.config?.rename_template || "{country_name} {protocol} {validated_date} #{index}";
  } catch (error) {
    toast(error.message);
  }
}

async function refreshSubscriptions() {
  try {
    const data = await jsonFetch(api("/api/subscriptions"));
    renderSubscriptions(data.subscriptions || []);
  } catch (error) {
    toast(error.message);
  }
}

function renderConverterTargets(targets = []) {
  const current = $("converterTarget").value;
  $("converterTarget").innerHTML = targets.map((target) => (
    `<option value="${escapeHtml(target.id)}">${escapeHtml(target.name)}</option>`
  )).join("");
  if (current && targets.some((target) => target.id === current)) {
    $("converterTarget").value = current;
  }
}

function renderConverterInputTypes(inputTypes = []) {
  const current = $("converterInputType").value || "auto";
  $("converterInputType").innerHTML = inputTypes.map((item) => (
    `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`
  )).join("");
  if (inputTypes.some((item) => item.id === current)) {
    $("converterInputType").value = current;
  }
}

function renderConverterLogs(logs = []) {
  const last = logs[0] || null;
  setText("converterMetricLast", last ? (last.status || "-") : "-");
  setText("converterMetricLastMsg", last ? (last.message || "无消息") : "暂无转换日志");
  setText("converterMetricNodes", String(last?.node_count || 0));
  setText("converterMetricBytes", `输入 ${last?.input_bytes || 0}B / 输出 ${last?.output_bytes || 0}B`);
  $("converterLogs").innerHTML = logs.length ? logs.map((item) => `
    <article class="converter-log ${escapeHtml(item.status || "")}">
      <div><strong>${escapeHtml(item.target_name || item.target_id || "-")}</strong><span>${escapeHtml(item.status || "")}</span></div>
      <p>${escapeHtml(item.message || "")}</p>
      <small>${escapeHtml(item.created_at || "")} | ${escapeHtml(item.input_mode || "")} | ${escapeHtml(item.input_type || "auto")} | 节点 ${item.node_count || 0} | 输入 ${item.input_bytes || 0}B | 输出 ${item.output_bytes || 0}B</small>
    </article>
  `).join("") : `<p class="hint">暂无转换日志。</p>`;
}

function renderConverterHealth(health = null) {
  if (!health) {
    $("converterHealth").textContent = "尚未检查 Sub-Store 服务状态。";
    $("converterHealth").classList.remove("ok", "error");
    setText("converterMetricState", "未检查");
    setText("converterMetricBackend", "等待 Sub-Store 状态");
    setPipelineStage("stageConvert", "warning", "未检查");
    return;
  }
  $("converterHealth").textContent = `${health.ok ? "服务可达" : "服务不可达"} | ${health.backend_url || ""} | ${health.message || ""} | ${health.latency_ms || 0} ms`;
  setText("converterMetricState", health.ok ? "可用" : "异常");
  setText("converterMetricBackend", `${health.backend_url || ""} | ${health.latency_ms || 0} ms`);
  $("converterHealth").classList.toggle("ok", !!health.ok);
  $("converterHealth").classList.toggle("error", !health.ok);
  setPipelineStage("stageConvert", health.ok ? "ok" : "error", health.ok ? "服务可达" : "不可达");
  setButtonLight("navSubscription", health.ok ? "ok" : "warning");
}

function applyConverterConfig(config = {}, targets = [], projectUrl = "", inputTypes = [], logs = []) {
  $("converterBackendUrl").value = config.backend_url || "http://127.0.0.1:3001";
  $("converterProfileName").value = config.profile_name || "sub";
  $("converterExportLimit").value = config.export_limit ?? 20;
  $("converterPreferAsia").checked = config.prefer_asia !== false;
  renderConverterTargets(targets);
  renderConverterInputTypes(inputTypes);
  renderConverterLogs(logs);
  $("converterNotice").textContent = `当前轻量调用 ${projectUrl || "Sub-Store"} 的下载转换接口，不会把完整仓库下载到本项目。`;
  renderConverterHealth(null);
  updateConverterInputMode();
}

function converterPayload() {
  return {
    backend_url: $("converterBackendUrl").value,
    profile_name: $("converterProfileName").value,
    export_limit: $("converterExportLimit").value,
    prefer_asia: $("converterPreferAsia").checked,
  };
}

async function refreshConverterConfig() {
  try {
    const data = await jsonFetch(api("/api/subscription-converter/config"));
    applyConverterConfig(data.config || {}, data.targets || [], data.project_url || "", data.input_types || [], data.logs || []);
  } catch (error) {
    toast(error.message);
  }
}

async function refreshPublishPool() {
  try {
    const data = await jsonFetch(api("/api/publish-pool"));
    renderPublishPool(data);
  } catch (error) {
    toast(error.message);
  }
}

function publishNodeCard(node = {}, actions = "") {
  const compatible = node.publish_compatible !== false;
  const state = node.publish_enabled ? "已发布" : (node.manual_status === "rejected" ? "不可发布" : "候选");
  const reason = node.publish_block_reason ? `；${escapeHtml(node.publish_block_reason)}` : "";
  return `
    <article class="profile-card ${compatible ? "" : "failed"}">
      <div class="node-meta">
        <span class="protocol">${escapeHtml(node.protocol || "-")}</span>
        <span>地区 ${escapeHtml(node.country || "未知")}</span>
        <span>${escapeHtml(state)}</span>
      </div>
      <div class="node-name">${escapeHtml(node.name || node.server || "未命名节点")}</div>
      <div class="node-meta">
        <span>server ${escapeHtml(node.server || "-")}</span>
        <span>port ${escapeHtml(node.port || "-")}</span>
        <span>network ${escapeHtml(node.network || "-")}</span>
        <span>TLS ${node.tls ? "yes" : "no"}</span>
      </div>
      <div class="node-meta">
        <span>VPS ${escapeHtml(node.validation_status || "valid")}</span>
        <span>延迟 ${Number(node.latency_ms || 0)} ms</span>
        <span>source ${escapeHtml(node.source_type || "-")}</span>
        <span>${node.cf_candidate ? "CF 候选" : "非 CF"}</span>
        <span>${node.manual_added ? "手动添加" : "自动来源"}</span>
        <span>${compatible ? "可验收" : "默认不发布"}${reason}</span>
      </div>
      ${actions ? `<div class="actions compact-actions">${actions}</div>` : ""}
    </article>
  `;
}

function renderPublishPool(data = {}) {
  const candidates = data.candidates || [];
  const published = data.published || [];
  const count = Number(data.publish_count || published.length || 0);
  setText("subscriptionMetricPublish", count.toLocaleString());
  setText("publishPoolSummary", `发布池 ${count.toLocaleString()} 条；候选 ${Number(data.candidate_count || candidates.length || 0).toLocaleString()} 条。Bot 订阅只从发布池输出。`);
  const candidateTarget = $("publishCandidates");
  const poolTarget = $("publishPoolList");
  if (candidateTarget) {
    candidateTarget.innerHTML = candidates.length ? candidates.map((node) => publishNodeCard(node, `
      <button class="primary" data-publish-mark="1" data-uri="${escapeHtml(node.uri || "")}" ${node.publish_compatible === false ? "disabled" : ""}>标记可发布</button>
      <button class="ghost" data-publish-mark="0" data-uri="${escapeHtml(node.uri || "")}">标记不可发布</button>
      <button class="ghost" data-publish-remove="${escapeHtml(node.uri || "")}">移出发布池</button>
    `)).join("") : `<p class="hint">暂无优质候选节点。请先运行采集和 VPS 验证。</p>`;
  }
  if (poolTarget) {
    poolTarget.innerHTML = published.length ? published.map((node) => publishNodeCard(node, `
      <button class="ghost" data-publish-mark="0" data-uri="${escapeHtml(node.uri || "")}">标记不可发布</button>
      <button class="danger" data-publish-remove="${escapeHtml(node.uri || "")}">移出发布池</button>
    `)).join("") : `<p class="hint">发布池为空。Bot 会提示“正在筛选中”，不会兜底发普通有效节点。</p>`;
  }
  bindPublishPoolActions();
}

function bindPublishPoolActions() {
  document.querySelectorAll("[data-publish-mark]").forEach((button) => {
    button.onclick = async () => {
      const publishable = button.dataset.publishMark === "1";
      const data = await post(api("/api/publish-pool/mark"), { uri: button.dataset.uri || "", publishable });
      if (data) {
        renderPublishPool(data);
        toast(publishable ? "已标记为可发布" : "已标记为不可发布");
      }
    };
  });
  document.querySelectorAll("[data-publish-remove]").forEach((button) => {
    button.onclick = async () => {
      const data = await post(api("/api/publish-pool/remove"), { uri: button.dataset.publishRemove || "" });
      if (data) {
        renderPublishPool(data);
        toast("已移出发布池");
      }
    };
  });
}

async function saveConverterConfig() {
  try {
    const data = await jsonFetch(api("/api/subscription-converter/config"), {
      method: "POST",
      body: JSON.stringify(converterPayload()),
    });
    applyConverterConfig(data.config || {}, data.targets || [], data.project_url || "", data.input_types || [], data.logs || []);
    toast("订阅转换配置已保存");
  } catch (error) {
    toast(error.message);
  }
}

async function checkConverterHealth() {
  try {
    const data = await jsonFetch(api("/api/subscription-converter/health"), {
      method: "POST",
      body: JSON.stringify({ backend_url: $("converterBackendUrl").value }),
    });
    renderConverterHealth(data.health || null);
    renderConverterLogs(data.logs || []);
    toast(data.health?.ok ? "Sub-Store 服务可达" : "Sub-Store 服务不可达");
  } catch (error) {
    toast(error.message);
    await refreshConverterConfig();
  }
}

function updateConverterInputMode() {
  const custom = $("converterInputMode").value === "custom";
  $("converterInput").disabled = !custom;
  if (!custom) {
    $("converterInput").value = "";
    $("converterInput").placeholder = "将使用数据库有效节点池，无需粘贴内容。";
  } else {
    $("converterInput").placeholder = "在这里粘贴原始订阅、节点 URI 或 Base64 内容。";
  }
}

async function convertSubscription() {
  try {
    const data = await jsonFetch(api("/api/subscription-converter/convert"), {
      method: "POST",
      body: JSON.stringify({
        ...converterPayload(),
        target: $("converterTarget").value,
        input_mode: $("converterInputMode").value,
        input_type: $("converterInputType").value,
        content: $("converterInput").value,
      }),
    });
    $("converterOutput").value = data.content || "";
    const cacheText = data.cache?.hit ? "缓存命中" : "新转换并写入缓存";
    $("converterSummary").textContent = `已转换为 ${data.target || ""}：输入 ${data.node_count || 0} 条，输出 ${data.bytes || 0} 字节，${cacheText}。`;
    renderConverterLogs(data.logs || []);
    toast("订阅转换完成");
  } catch (error) {
    toast(error.message);
    await refreshConverterConfig();
  }
}

async function copyConvertedSubscription() {
  const value = $("converterOutput").value;
  if (!value) {
    toast("请先转换订阅");
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    toast("转换结果已复制");
  } catch (error) {
    $("converterOutput").select();
    document.execCommand("copy");
    toast("转换结果已复制");
  }
}

function maintenancePayload() {
  return {
    enabled: $("maintenanceEnabled").checked,
    schedule_hour: $("maintenanceHour").value,
    schedule_minute: $("maintenanceMinute").value,
    converter_log_days: $("converterLogDays").value,
    converter_log_max_rows: $("converterLogMaxRows").value,
    bot_log_days: $("botLogDays").value,
    bot_log_max_rows: $("botLogMaxRows").value,
    claim_record_days: $("claimRecordDays").value,
    subscription_access_days: $("subscriptionAccessDays").value,
    subscription_access_max_rows: $("subscriptionAccessMaxRows").value,
    stale_unvalidated_node_days: $("staleUnvalidatedNodeDays").value,
    invalid_node_days: $("invalidNodeDays").value,
    bot_verification_days: $("botVerificationDays").value,
    conversion_cache_days: $("conversionCacheDays").value,
    conversion_cache_max_rows: $("conversionCacheMaxRows").value,
    daily_stats_days: $("dailyStatsDays").value,
    acceptance_report_days: $("acceptanceReportDays").value,
    acceptance_failed_report_days: $("acceptanceFailedReportDays").value,
    acceptance_report_max_files: $("acceptanceReportMaxFiles").value,
    maintenance_record_days: $("maintenanceRecordDays").value,
    vacuum_after_cleanup: $("vacuumAfterCleanup").checked,
  };
}

function applyMaintenanceConfig(config = {}) {
  $("maintenanceEnabled").checked = config.enabled !== false;
  $("maintenanceHour").value = config.schedule_hour ?? 3;
  $("maintenanceMinute").value = config.schedule_minute ?? 30;
  $("converterLogDays").value = config.converter_log_days ?? 7;
  $("converterLogMaxRows").value = config.converter_log_max_rows ?? 5000;
  $("botLogDays").value = config.bot_log_days ?? 7;
  $("botLogMaxRows").value = config.bot_log_max_rows ?? 10000;
  $("claimRecordDays").value = config.claim_record_days ?? 7;
  $("subscriptionAccessDays").value = config.subscription_access_days ?? 7;
  $("subscriptionAccessMaxRows").value = config.subscription_access_max_rows ?? 20000;
  $("staleUnvalidatedNodeDays").value = config.stale_unvalidated_node_days ?? 2;
  $("invalidNodeDays").value = config.invalid_node_days ?? 30;
  $("botVerificationDays").value = config.bot_verification_days ?? 7;
  $("conversionCacheDays").value = config.conversion_cache_days ?? 7;
  $("conversionCacheMaxRows").value = config.conversion_cache_max_rows ?? 1000;
  $("dailyStatsDays").value = config.daily_stats_days ?? 365;
  $("acceptanceReportDays").value = config.acceptance_report_days ?? 7;
  $("acceptanceFailedReportDays").value = config.acceptance_failed_report_days ?? 30;
  $("acceptanceReportMaxFiles").value = config.acceptance_report_max_files ?? 300;
  $("maintenanceRecordDays").value = config.maintenance_record_days ?? 180;
  $("vacuumAfterCleanup").checked = !!config.vacuum_after_cleanup;
}

function renderMaintenance(overview = {}) {
  applyMaintenanceConfig(overview.config || {});
  $("databaseSize").textContent = formatBytes(overview.database_bytes || 0);
  const files = overview.files || {};
  $("runtimeLogSize").textContent = formatBytes(files.runtime_logs?.bytes || 0);
  $("acceptanceReportSize").textContent = formatBytes(files.acceptance_reports?.bytes || 0);
  setPipelineStage("stageMaintenance", overview.config?.enabled === false ? "warning" : "ok", overview.config?.enabled === false ? "已关闭" : "自动维护");
  setButtonLight("navSettings", overview.config?.enabled === false ? "warning" : "ok");
  const last = overview.last_cleanup || overview.result || null;
  $("lastCleanupRows").textContent = String(last?.deleted_rows ?? 0);
  const conversionCache = overview.conversion_cache || {};
  $("conversionCacheRows").textContent = Number(conversionCache.rows || 0).toLocaleString();
  $("conversionCacheHits").textContent = Number(conversionCache.hits || 0).toLocaleString();
  setText("dashConversionCache", Number(conversionCache.rows || 0).toLocaleString());
  setText("converterMetricCache", Number(conversionCache.hits || 0).toLocaleString());
  const counts = overview.table_counts || {};
  $("maintenanceTableCounts").innerHTML = Object.keys(counts).length ? Object.entries(counts).map(([name, count]) => `
    <article class="profile-item">
      <strong>${escapeHtml(name)}</strong>
      <span>${Number(count || 0).toLocaleString()} 条</span>
    </article>
  `).join("") : "<p class=\"hint\">暂无表统计。</p>";
  const dailyStats = overview.daily_stats || [];
  $("dailyStatsList").innerHTML = dailyStats.length ? dailyStats.slice(0, 12).map((item) => `
    <article class="profile-item">
      <strong>${escapeHtml(item.stat_date || "-")} / ${escapeHtml(item.category || "-")}</strong>
      <span>${escapeHtml(item.name || "-")}?${Number(item.count || 0).toLocaleString()}</span>
    </article>
  `).join("") : '<p class="hint">&#26242;&#26080;&#38271;&#26399;&#32479;&#35745;&#65292;&#25191;&#34892;&#19968;&#27425;&#32500;&#25252;&#21518;&#29983;&#25104;&#12290;</p>';
  $("maintenanceLastCleanup").textContent = last
    ? `时间：${last.created_at || "-"}\n原因：${last.reason || "-"}\n清理：${last.deleted_rows || 0} 条\n清理前：${formatBytes(last.database_bytes_before || 0)}\n清理后：${formatBytes(last.database_bytes_after || 0)}\n详情：${typeof last.details === "string" ? last.details : JSON.stringify(last.details || {})}`
    : "暂无维护记录";
}

function acceptancePayload() {
  return {
    collect_target: $("acceptanceCollectTarget").value,
    valid_target: $("acceptanceValidTarget").value,
    claim_rounds: $("acceptanceClaimRounds").value,
    claim_rate_per_minute: $("acceptanceClaimRate").value,
    keyword: $("acceptanceKeyword").value,
    code: $("acceptanceCode").value,
    skip_collect: $("acceptanceSkipCollect").checked,
    skip_validate: $("acceptanceSkipValidate").checked,
    smoke: $("acceptanceSmoke").checked,
    keep_test_subscriptions: $("acceptanceKeepSubscriptions").checked,
  };
}

function renderAcceptance(data = {}) {
  const running = !!data.task?.running;
  taskBadge("acceptanceBadge", running);
  setLight("acceptanceLight", running);
  setButtonLight("startAcceptance", running ? "running" : "ok");
  setButtonLight("stopAcceptance", running ? "error" : "off");
  $("acceptanceState").textContent = running ? `运行中，PID ${data.task?.pid || ""}` : "已停止";
  const latest = data.latest || {};
  const summary = latest.summary || {};
  $("acceptanceTotal").textContent = summary.total ?? 0;
  $("acceptanceSuccess").textContent = summary.success ?? 0;
  $("acceptanceFailed").textContent = summary.failed ?? 0;
  $("acceptanceNotice").textContent = latest.file
    ? `最近报告：${latest.file}，结束时间 ${latest.finished_at || "未知"}`
    : "通过现有后台 API、BOT 模拟、公开订阅入口和 Sub-Store 转换接口执行，不重写业务逻辑。";
  const byTarget = summary.by_target || {};
  $("acceptanceTargetStats").innerHTML = Object.keys(byTarget).length ? Object.entries(byTarget).map(([target, item]) => `
    <article class="profile-card">
      <strong>${escapeHtml(target)}</strong>
      <span>总数 ${item.total || 0}，成功 ${item.success || 0}，失败 ${item.failed || 0}</span>
    </article>
  `).join("") : "<p class=\"empty\">暂无格式统计。</p>";
  $("acceptanceReports").innerHTML = (data.reports || []).length ? (data.reports || []).map((report) => {
    const item = report.summary || {};
    return `
      <article class="profile-card">
        <strong>${escapeHtml(report.file || "验收报告")}</strong>
        <span>${escapeHtml(report.started_at || "")} - ${escapeHtml(report.finished_at || "")}</span>
        <span>领取 ${item.total || 0}，成功 ${item.success || 0}，失败 ${item.failed || 0}</span>
      </article>
    `;
  }).join("") : "<p class=\"empty\">暂无验收报告。</p>";
}

async function refreshAcceptance() {
  try {
    const data = await jsonFetch(api("/api/acceptance"));
    renderAcceptance(data);
  } catch (error) {
    toast(error.message);
  }
}

async function startAcceptance() {
  try {
    const data = await jsonFetch(api("/api/acceptance/start"), {
      method: "POST",
      body: JSON.stringify(acceptancePayload()),
    });
    renderAcceptance(data.status || {});
    toast(data.changed ? "真实验收已启动" : (data.reason || "真实验收未启动"));
  } catch (error) {
    toast(error.message);
  }
}

async function stopAcceptance() {
  try {
    const data = await jsonFetch(api("/api/acceptance/stop"), { method: "POST", body: "{}" });
    renderAcceptance(data.status || {});
    toast("已请求停止真实验收");
  } catch (error) {
    toast(error.message);
  }
}

async function refreshMaintenance() {
  try {
    const data = await jsonFetch(api("/api/maintenance"));
    renderMaintenance(data);
  } catch (error) {
    toast(error.message);
  }
}

let xrayReleases = [];

async function refreshRuntimeStatus() {
  try {
    const data = await jsonFetch(api("/api/xray/runtime"));
    const runtime = data.xray || {};
    const available = !!runtime.available;
    const path = runtime.path || "-";
    const geoip = `${runtime.geoip_available ? "GeoIP 可用" : "GeoIP 缺失"} / ${runtime.geosite_available ? "GeoSite 可用" : "GeoSite 缺失"}`;
    $("xrayCurrentPath").textContent = typeof path === "string" ? path : JSON.stringify(path);
    $("xrayCurrentVersion").textContent = runtime.version || "-";
    $("xrayGeoipPath").textContent = typeof geoip === "string" ? geoip : JSON.stringify(geoip);
    $("xrayAvailableBadge").textContent = available ? "可用" : "不可用";
    $("xrayAvailableBadge").classList.toggle("running", available);
    renderXrayLocalVersions(data.local || []);
  } catch (error) {
    $("xrayAvailableBadge").textContent = "检查失败";
    toast(error.message);
  }
}

function renderXrayReleaseOptions() {
  const releaseSelect = $("xrayReleaseSelect");
  releaseSelect.innerHTML = xrayReleases.length
    ? xrayReleases.map((item, index) => `<option value="${index}">${escapeHtml(item.version || item.name || "-")} ${item.prerelease ? "(预发布)" : ""}</option>`).join("")
    : '<option value="">请先拉取官方版本</option>';
  renderXrayAssetOptions();
}

function renderXrayAssetOptions() {
  const index = Number($("xrayReleaseSelect").value || 0);
  const release = xrayReleases[index] || {};
  const assets = release.assets || [];
  const sorted = assets.slice().sort((a, b) => Number(b.matched) - Number(a.matched));
  $("xrayAssetSelect").innerHTML = sorted.length
    ? sorted.map((asset, assetIndex) => `<option value="${assetIndex}">${asset.matched ? "推荐 | " : ""}${escapeHtml(asset.name)}</option>`).join("")
    : '<option value="">当前版本没有可下载包</option>';
  $("xrayAssetSelect").dataset.assets = JSON.stringify(sorted);
}

async function loadXrayReleases() {
  try {
    const platform = encodeURIComponent($("xrayPlatform").value);
    const arch = encodeURIComponent($("xrayArch").value);
    const data = await jsonFetch(api(`/api/xray/releases?platform=${platform}&arch=${arch}&limit=30`));
    xrayReleases = data.releases || [];
    renderXrayReleaseOptions();
    toast(`已拉取 Xray 官方版本 ${xrayReleases.length} 个`);
  } catch (error) {
    toast(error.message);
  }
}

async function downloadXrayRelease() {
  const release = xrayReleases[Number($("xrayReleaseSelect").value || 0)] || {};
  const assets = JSON.parse($("xrayAssetSelect").dataset.assets || "[]");
  const asset = assets[Number($("xrayAssetSelect").value || 0)] || {};
  if (!release.version || !asset.download_url) {
    toast("请先选择官方版本和下载包");
    return;
  }
  try {
    const data = await jsonFetch(api("/api/xray/download"), {
      method: "POST",
      body: JSON.stringify({ version: release.version, asset_url: asset.download_url, asset_name: asset.name }),
    });
    renderXrayLocalVersions(data.local || []);
    toast("Xray 已下载，当前内核未自动切换");
  } catch (error) {
    toast(error.message);
  }
}

function renderXrayLocalVersions(items = []) {
  $("xrayLocalVersions").innerHTML = items.length ? items.map((item) => `
    <article class="profile-card">
      <div class="node-meta">
        <span class="protocol">${escapeHtml(item.version || "-")}</span>
        <span>${item.available ? "可用" : "不可用"}</span>
        <span>${item.active ? "当前使用" : "未启用"}</span>
      </div>
      <div class="node-uri">${escapeHtml(item.executable || item.path || "")}</div>
      <div class="actions compact-actions">
        <button class="ghost" data-activate-xray="${escapeHtml(item.version || "")}" ${item.active || !item.available ? "disabled" : ""}>设为当前</button>
      </div>
    </article>
  `).join("") : '<p class="hint">暂无本地下载版本。请先拉取官方版本并下载。</p>';
  document.querySelectorAll("[data-activate-xray]").forEach((button) => {
    button.onclick = async () => {
      if (!confirm("确认切换当前 Xray 内核吗？下载和切换是分开的，切换会影响后续验证任务。")) return;
      try {
        const data = await jsonFetch(api("/api/xray/activate"), {
          method: "POST",
          body: JSON.stringify({ version: button.dataset.activateXray }),
        });
        renderXrayLocalVersions(data.local || []);
        await refreshRuntimeStatus();
        toast("Xray 当前版本已切换");
      } catch (error) {
        toast(error.message);
      }
    };
  });
}

async function saveMaintenanceConfig() {
  try {
    const data = await jsonFetch(api("/api/maintenance/config"), {
      method: "POST",
      body: JSON.stringify(maintenancePayload()),
    });
    renderMaintenance(data);
    toast("系统维护配置已保存");
  } catch (error) {
    toast(error.message);
  }
}

async function runMaintenanceCleanup() {
  try {
    const data = await jsonFetch(api("/api/maintenance/cleanup"), {
      method: "POST",
      body: "{}",
    });
    renderMaintenance(data);
    toast(`维护完成，清理 ${data.result?.deleted_rows || 0} 条记录`);
  } catch (error) {
    toast(error.message);
  }
}

async function clearConversionCache() {
  try {
    const data = await jsonFetch(api("/api/subscription-converter/cache/clear"), {
      method: "POST",
      body: "{}",
    });
    renderMaintenance(data.maintenance || {});
    toast(`转换缓存已清空：${data.deleted || 0} 条`);
  } catch (error) {
    toast(error.message);
  }
}

function subscriptionPayload() {
  return {
    name: $("subscriptionName").value,
    mode: $("subscriptionMode").value,
    max_uses: $("subscriptionMaxUses").value,
    export_limit: $("subscriptionExportLimit").value,
    expires_at: $("subscriptionExpiresAt").value,
    rename_template: $("subscriptionTemplate").value,
    remark: $("subscriptionRemark").value,
  };
}

async function createSubscription() {
  try {
    const data = await jsonFetch(api("/api/subscriptions"), {
      method: "POST",
      body: JSON.stringify(subscriptionPayload()),
    });
    const target = $("subscriptionDefaultTarget").value || "base64";
    const url = subscriptionUrlForTarget(data.subscription || {}, target);
    try {
      await navigator.clipboard?.writeText(url);
    } catch (error) {
      // Clipboard permissions vary by browser; creation itself has already succeeded.
    }
    toast(`${subscriptionTargetName(data.subscription || {}, target)} 订阅链接已生成并复制`);
    await refreshSubscriptions();
  } catch (error) {
    toast(error.message);
  }
}

function subscriptionUrlForTarget(item = {}, target = "base64") {
  const formats = item.format_urls || [];
  const match = formats.find((format) => format.id === target) || formats.find((format) => format.id === "base64");
  return match?.url || item.url || "";
}

function subscriptionTargetName(item = {}, target = "base64") {
  const formats = item.format_urls || [];
  const match = formats.find((format) => format.id === target) || formats.find((format) => format.id === "base64");
  return match?.name || target;
}

function currentSubscriptionItem(token) {
  return currentSubscriptions.find((item) => item.token === token) || {};
}

function subscriptionFormatSelect(token) {
  return Array.from(document.querySelectorAll("[data-subscription-format]"))
    .find((select) => select.dataset.subscriptionFormat === token) || null;
}

function renderSubscriptions(items) {
  currentSubscriptions = items;
  const enabledCount = items.filter((item) => item.enabled !== false).length;
  const currentClaimVersion = items.find((item) => item.current_claim_code_version)?.current_claim_code_version
    || items.find((item) => item.claim_code_version)?.claim_code_version
    || "-";
  setText("subscriptionMetricLinks", String(items.length));
  setText("subscriptionMetricEnabled", `启用 ${enabledCount}`);
  setText("dashSubscriptionLinks", String(items.length));
  setText("dashSubscriptionEnabled", `启用 ${enabledCount}`);
  setText("subscriptionMetricLimit", $("subscriptionExportLimit")?.value || "20");
  setText("subscriptionMetricClaimVersion", currentClaimVersion);
  $("subscriptionList").innerHTML = items.length ? items.map((item) => {
    const formatUrls = item.format_urls || [];
    const selectedTarget = $("subscriptionDefaultTarget")?.value || "base64";
    const selectedUrl = subscriptionUrlForTarget(item, selectedTarget);
    return `
    <article class="subscription-card">
      <div class="node-meta">
        <span class="protocol">${escapeHtml(item.status)}</span>
        <span>${item.mode === "usage" ? "按次数" : item.mode === "time" ? "按时间" : "次数或时间"}</span>
        <span>已用 ${item.used_count || 0}${item.max_uses ? " / " + item.max_uses : ""}</span>
        <span>导出 ${item.export_limit || 20} 条</span>
        <span>口令 ${escapeHtml(item.claim_code_version || "未绑定")} / 当前 ${escapeHtml(item.current_claim_code_version || "-")}</span>
        <span>过期 ${escapeHtml(item.expires_at || "不按时间")}</span>
        <span>最后访问 ${escapeHtml(item.last_used_at || "未访问")}</span>
      </div>
      <div class="node-name">${escapeHtml(item.name || "")}</div>
      <div class="subscription-main-link">
        <select data-subscription-format="${escapeHtml(item.token)}">
          ${formatUrls.map((format) => `<option value="${escapeHtml(format.id || "base64")}" ${format.id === selectedTarget ? "selected" : ""}>${escapeHtml(format.name || format.id || "订阅")}</option>`).join("")}
        </select>
        <div class="node-uri" id="subscriptionUrl-${escapeHtml(item.token)}">${escapeHtml(selectedUrl)}</div>
      </div>
      <pre class="result-box subscription-test-result" id="subscriptionTest-${escapeHtml(item.token)}" hidden></pre>
      <div class="node-meta">${escapeHtml(item.remark || "无备注")}</div>
      <div class="actions compact-actions">
        <button class="ghost" data-copy-current-subscription="${escapeHtml(item.token)}">复制链接</button>
        <button class="ghost" data-test-current-subscription="${escapeHtml(item.token)}">测试</button>
        <button class="ghost" data-toggle-subscription="${escapeHtml(item.token)}" data-enabled="${item.enabled ? "0" : "1"}">${item.enabled ? "禁用" : "启用"}</button>
        <button class="danger" data-delete-subscription="${escapeHtml(item.token)}">删除</button>
      </div>
    </article>
  `}).join("") : `<p class="hint">暂无订阅链接。生成后会显示在这里。</p>`;
  bindSubscriptionActions();
}

function bindSubscriptionActions() {
  document.querySelectorAll("[data-subscription-format]").forEach((select) => {
    select.onchange = () => {
      const token = select.dataset.subscriptionFormat || "";
      const item = currentSubscriptionItem(token);
      const target = select.value || "base64";
      const output = document.getElementById(`subscriptionUrl-${token}`);
      if (output) output.textContent = subscriptionUrlForTarget(item, target);
      const testOutput = document.getElementById(`subscriptionTest-${token}`);
      if (testOutput) testOutput.hidden = true;
    };
  });
  document.querySelectorAll("[data-copy-current-subscription]").forEach((button) => {
    button.onclick = async () => {
      const token = button.dataset.copyCurrentSubscription || "";
      const target = subscriptionFormatSelect(token)?.value || "base64";
      const item = currentSubscriptionItem(token);
      await navigator.clipboard.writeText(subscriptionUrlForTarget(item, target));
      toast(`${subscriptionTargetName(item, target)} 链接已复制`);
    };
  });
  document.querySelectorAll("[data-toggle-subscription]").forEach((button) => {
    button.onclick = async () => {
      const token = button.dataset.toggleSubscription;
      const action = button.dataset.enabled === "1" ? "enable" : "disable";
      await post(api(`/api/subscriptions/${token}/${action}`));
      await refreshSubscriptions();
    };
  });
  document.querySelectorAll("[data-test-current-subscription]").forEach((button) => {
    button.onclick = async () => {
      const token = button.dataset.testCurrentSubscription || "";
      const target = subscriptionFormatSelect(token)?.value || "base64";
      const output = document.getElementById(`subscriptionTest-${token}`);
      if (output) {
        output.hidden = false;
        output.textContent = "正在测试订阅格式...";
      }
      try {
        const data = await jsonFetch(api(`/api/subscriptions/${token}/test`), {
          method: "POST",
          body: JSON.stringify({ target }),
        });
        if (output) {
          output.textContent = [
            `格式：${data.target_name || data.target_id}`,
            `节点：${data.node_count || 0}`,
            `大小：${data.bytes || 0}B`,
            `耗时：${data.elapsed_ms || 0}ms`,
            `类型：${data.content_type || ""}`,
            data.truncated ? "预览：前 1200 字符" : "预览：完整内容",
            "",
            data.preview || "",
          ].join("\n");
        }
        toast(`${data.target_name || target} 测试完成`);
      } catch (error) {
        if (output) output.textContent = error.message;
        toast(error.message);
      }
    };
  });
  document.querySelectorAll("[data-delete-subscription]").forEach((button) => {
    button.onclick = async () => {
      if (!confirm("确定删除这条订阅链接吗？删除后无法恢复。")) return;
      await post(api(`/api/subscriptions/${button.dataset.deleteSubscription}/delete`));
      await refreshSubscriptions();
    };
  });
}

function updateSubscriptionMode() {
  const mode = $("subscriptionMode").value;
  $("subscriptionMaxUses").disabled = mode === "time";
  $("subscriptionExpiresAt").disabled = mode === "usage";
}

async function refreshProcessingPreview() {
  try {
    const data = await jsonFetch(api("/api/node-processing/preview?limit=20"));
    renderProcessingPreview(data.nodes || []);
  } catch (error) {
    toast(error.message);
  }
}

async function saveRenameTemplate() {
  try {
    const data = await jsonFetch(api("/api/node-processing/config"), {
      method: "POST",
      body: JSON.stringify({ rename_template: $("renameTemplate").value }),
    });
    $("renameTemplate").value = data.config?.rename_template || $("renameTemplate").value;
    toast("节点名字模板已保存");
    await previewRenameTemplate();
  } catch (error) {
    toast(error.message);
  }
}

async function previewRenameTemplate() {
  try {
    const data = await jsonFetch(api("/api/node-processing/preview"), {
      method: "POST",
      body: JSON.stringify({ rename_template: $("renameTemplate").value, limit: 20 }),
    });
    renderProcessingPreview(data.nodes || []);
  } catch (error) {
    toast(error.message);
  }
}

async function exportRawNodes() {
  try {
    const response = await fetch(api("/api/subscription/raw"), { credentials: "same-origin" });
    if (!response.ok) throw new Error(`请求失败：${response.status}`);
    const text = await response.text();
    $("subscriptionOutput").value = text;
    $("exportSummary").textContent = `已导出原始节点：${text.split(/\r?\n/).filter(Boolean).length} 条。未应用重命名模板。`;
    toast("原始节点已导出");
  } catch (error) {
    toast(error.message);
  }
}

async function copySubscription() {
  const value = $("subscriptionOutput").value;
  if (!value) {
    toast("请先导出原始节点");
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    toast("导出内容已复制");
  } catch (error) {
    $("subscriptionOutput").select();
    document.execCommand("copy");
    toast("导出内容已复制");
  }
}

function renderProcessingPreview(nodes) {
  $("processingPreview").innerHTML = nodes.length ? nodes.map((node) => `
    <article class="node-card">
      <div class="node-meta"><span class="protocol">${escapeHtml(node.protocol || "")}</span><span>国家 ${escapeHtml(node.country || "未知")}</span><span>出口 ${escapeHtml(node.proxy_ips || "未知")}</span></div>
      <div class="node-name">${escapeHtml(node.name)}</div>
      <div class="node-uri">${escapeHtml(node.uri)}</div>
    </article>`).join("") : `<p class="hint">暂无可预览的有效节点。</p>`;
}

function updateSelectOptions(id, values, allLabel) {
  const select = $(id);
  const current = select.value;
  const options = [`<option value="">${allLabel}</option>`].concat(values.map((value) => {
    const escaped = escapeHtml(value);
    return `<option value="${escaped}">${escaped}</option>`;
  }));
  select.innerHTML = options.join("");
  if (values.includes(current)) select.value = current;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

function autoNoticeText(auto = {}, database = {}) {
  if (!auto.enabled) return "自动控制未开启。开启后会按分钟巡检有效节点库，低于阈值时优先验证库存，库存为空才采集补货。";
  const valid = database.valid_nodes || 0;
  const pending = database.pending_nodes ?? (database.total_nodes || 0);
  const low = auto.config?.valid_low_watermark ?? 0;
  const minutes = auto.config?.check_interval_minutes ?? 5;
  if (auto.phase === "collecting") return "正在采集补货：节点库为空且有效节点低于阈值，采集达到新增入库目标后会自动切到验证。";
  if (auto.phase === "validating") return "正在验证库存：采集与验证互斥运行，本轮新增有效节点达到目标后会自动停止。";
  if (valid < low && pending > 0) return `有效节点 ${valid} 低于阈值 ${low}，节点库还有 ${pending} 条库存，下一轮会优先验证。`;
  if (valid < low) return `有效节点 ${valid} 低于阈值 ${low}，节点库为空时会自动启动采集补货。`;
  return `有效节点 ${valid} 已达到阈值 ${low}，后台每 ${minutes} 分钟巡检一次。`;
}

function redirectToLogin() {
  window.location.href = `${BASE_PATH}/login`;
}

async function checkAuth() {
  try {
    const data = await jsonFetch(api("/api/me"));
    if (!data.authenticated) {
      redirectToLogin();
      return false;
    }
    currentUser = data.user;
    $("accountUsername").value = currentUser?.username || "";
    return true;
  } catch (error) {
    redirectToLogin();
    return false;
  }
}

async function logout() {
  await post(api("/api/logout"));
  if (eventSource) eventSource.close();
  redirectToLogin();
}

async function saveAccount() {
  try {
    const data = await jsonFetch(api("/api/account"), {
      method: "POST",
      body: JSON.stringify({ username: $("accountUsername").value, password: $("accountPassword").value }),
    });
    currentUser = data.user;
    $("accountPassword").value = "";
    $("accountDialog").close();
    toast("账号信息已保存");
  } catch (error) {
    toast(error.message);
  }
}

$("startCollector").onclick = () => post(api("/api/collector/start"), {
  workers: $("collectorWorkers").value,
  max_depth: $("collectorDepth").value,
  delay: $("collectorDelay").value,
  delay_jitter: $("collectorJitter").value,
  log_level: $("collectorLogLevel").value,
});
$("stopCollector").onclick = () => post(api("/api/collector/stop"));
$("clearPendingNodes").onclick = () => clearNodePool("pending");
$("clearValidNodes").onclick = () => clearNodePool("valid");
$("saveRepos").onclick = async () => {
  const repos = $("repoList").value.split(/\r?\n/);
  try {
    const data = await jsonFetch(api("/api/repos"), { method: "POST", body: JSON.stringify({ repos }) });
    $("repoList").value = (data.items || []).map((item) => item.repo).join("\n");
    $("repoCount").textContent = `${data.count} / ${data.total || data.count} 个启用`;
    renderRepoItems(data.items || []);
    toast("仓库画像已保存");
  } catch (error) {
    toast(error.message);
  }
};
$("resetRepos").onclick = async () => {
  try {
    const data = await jsonFetch(api("/api/repos/reset"), { method: "POST", body: "{}" });
    $("repoList").value = (data.items || []).map((item) => item.repo).join("\n");
    $("repoCount").textContent = `${data.count} / ${data.total || data.count} 个启用`;
    renderRepoItems(data.items || []);
    toast("已恢复默认仓库");
  } catch (error) {
    toast(error.message);
  }
};
$("startValidator").onclick = () => post(api("/api/validator/start"), {
  workers: $("validatorWorkers").value,
  limit: $("validatorLimit").value,
  rounds: $("validatorRounds").value,
  timeout: $("validatorTimeout").value,
  revalidate: $("validatorRevalidate").checked,
});
$("stopValidator").onclick = () => post(api("/api/validator/stop"));
$("recheckValidNodes").onclick = () => post(api("/api/validator/recheck-valid"), {
  workers: $("validatorWorkers").value,
  limit: $("validatorLimit").value,
  rounds: $("validatorRounds").value,
  timeout: $("validatorTimeout").value,
});
$("dashStartCollector").onclick = () => $("startCollector").click();
$("dashStartValidator").onclick = () => $("startValidator").click();
$("dashRecheckValid").onclick = () => $("recheckValidNodes").click();
$("dashClearConversionCache").onclick = () => $("clearConversionCache").click();
$("dashStopTasks").onclick = async () => {
  await post(api("/api/collector/stop"));
  await post(api("/api/validator/stop"));
};
$("saveAutoConfig").onclick = () => saveAutoConfig().catch((error) => toast(error.message));
$("startAuto").onclick = async () => {
  await post(api("/api/auto/start"), autoPayload());
  toast("自动控制已开启");
};
$("stopAuto").onclick = async () => {
  await post(api("/api/auto/stop"));
  toast("自动控制已关闭");
};
$("clearLogs").onclick = async () => {
  await post(api("/api/logs/clear"));
  logEvents.length = 0;
  renderLogs();
};
$("refreshNodes").onclick = refreshNodes;
$("importManualNodes").onclick = importManualNodes;
$("copyFilteredNodes").onclick = copyFilteredNodes;
$("refreshProfiles").onclick = refreshProfiles;
$("refreshProcessingPreview").onclick = previewRenameTemplate;
$("saveRenameTemplate").onclick = saveRenameTemplate;
$("previewRenameTemplate").onclick = previewRenameTemplate;
$("exportRawNodes").onclick = exportRawNodes;
$("copySubscription").onclick = copySubscription;
$("refreshSubscriptions").onclick = refreshSubscriptions;
$("createSubscription").onclick = createSubscription;
$("refreshPublishPool").onclick = refreshPublishPool;
$("clearPublishPool").onclick = async () => {
  if (!confirm("确定清空发布池吗？这不会删除节点库，只会停止对粉丝发放这些节点。")) return;
  const data = await post(api("/api/publish-pool/clear"));
  if (data) {
    renderPublishPool(data);
    toast("发布池已清空");
  }
};
$("refreshConverterConfig").onclick = refreshConverterConfig;
$("saveConverterConfig").onclick = saveConverterConfig;
$("checkConverterHealth").onclick = checkConverterHealth;
$("convertSubscription").onclick = convertSubscription;
$("copyConvertedSubscription").onclick = copyConvertedSubscription;
$("refreshMaintenance").onclick = refreshMaintenance;
$("saveMaintenanceConfig").onclick = saveMaintenanceConfig;
$("runMaintenanceCleanup").onclick = runMaintenanceCleanup;
$("clearConversionCache").onclick = clearConversionCache;
$("loadXrayReleases").onclick = loadXrayReleases;
$("downloadXrayRelease").onclick = downloadXrayRelease;
$("refreshRuntimeStatus").onclick = refreshRuntimeStatus;
$("xrayReleaseSelect").onchange = renderXrayAssetOptions;
$("xrayPlatform").onchange = () => { xrayReleases = []; renderXrayReleaseOptions(); };
$("xrayArch").onchange = () => { xrayReleases = []; renderXrayReleaseOptions(); };
$("refreshOpsStats").onclick = refreshOpsStats;
$("refreshAcceptance").onclick = refreshAcceptance;
$("startAcceptance").onclick = startAcceptance;
$("stopAcceptance").onclick = stopAcceptance;
$("saveClaimCodeConfig").onclick = saveClaimCodeConfig;
$("refreshClaimCodeConfig").onclick = refreshClaimCodeConfig;
$("testClaimCode").onclick = testClaimCode;
$("saveBotConfig").onclick = saveBotConfig;
$("startBot").onclick = () => post(api("/api/bot/start")).then(refreshBot);
$("stopBot").onclick = () => post(api("/api/bot/stop")).then(refreshBot);
$("disableBot").onclick = () => post(api("/api/bot/disable")).then(refreshBot);
$("refreshBot").onclick = refreshBot;
$("runBotSimulation").onclick = runBotSimulation;
$("runBotFlowSimulation").onclick = runBotFlowSimulation;
$("botSimChatType").onchange = syncBotSimulationChatDefaults;
$("subscriptionMode").onchange = updateSubscriptionMode;
$("converterInputMode").onchange = updateConverterInputMode;
$("logoutButton").onclick = logout;
$("accountButton").onclick = () => $("accountDialog").showModal();
$("closeAccount").onclick = () => $("accountDialog").close();
$("saveAccount").onclick = saveAccount;
$("previousPage").onclick = () => { if (page > 1) { page -= 1; refreshNodes(); } };
$("nextPage").onclick = () => { if (page * nodePageSize < nodeTotal) { page += 1; refreshNodes(); } };
$("validProtocol").onchange = () => { page = 1; refreshNodes(); };
$("validCountry").onchange = () => { page = 1; refreshNodes(); };
$("validGroup").onchange = () => { page = 1; refreshNodes(); };
document.querySelectorAll(".tab").forEach((button) => button.onclick = () => {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
  button.classList.add("active");
  logFilter = button.dataset.logSource;
  renderLogs();
});
document.querySelectorAll(".ops-tabs .page-tab").forEach((button) => button.onclick = () => setGroupedPage(button));

async function startDashboard() {
  refreshStatus.autoConfigLoaded = false;
  renderXrayReleaseOptions();
  setGroupedPage(document.querySelector(".ops-tabs .page-tab.active") || document.querySelector(".ops-tabs .page-tab"));
  await Promise.all([
    refreshStatus(),
    refreshRepos(),
    refreshProfiles(),
    refreshNodes(),
    refreshProcessingConfig(),
    refreshProcessingPreview(),
    refreshSubscriptions(),
    refreshPublishPool(),
    refreshConverterConfig(),
    refreshMaintenance(),
    refreshOpsStats(),
    refreshRuntimeStatus(),
    refreshAcceptance(),
    refreshClaimCodeConfig(),
    refreshBot(),
  ]);
  updateSubscriptionMode();
  connectLogs();
}

checkAuth().then((ok) => {
  if (ok) startDashboard();
});
setInterval(() => {
  if (currentUser) {
    refreshStatus();
    refreshNodes();
    refreshAcceptance();
  }
}, 3000);
setInterval(() => {
  if (currentUser) refreshOpsStats();
}, 60000);
