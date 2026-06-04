const $ = (id) => document.getElementById(id);
let page = 1;
let nodeTotal = 0;
let logFilter = "all";
const logEvents = [];
const nodePageSize = 20;
const BASE_PATH = window.location.pathname.startsWith("/adminhuage") ? "/adminhuage" : "";
let currentUser = null;
let eventSource = null;

function api(path) {
  return `${BASE_PATH}${path}`;
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 2600);
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
      detail = payload.reason || payload.error || "";
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

function phaseText(phase) {
  return {
    idle: "空闲",
    collecting: "采集中",
    validating: "验证中",
    stopping: "停止中",
    stopping_collector: "停止采集",
    stopping_validator: "停止验证",
    error: "异常",
  }[phase] || phase || "未知";
}

function applyAutoConfig(config = {}) {
  $("autoValidLow").value = config.valid_low_watermark ?? 20;
  $("autoCollectTarget").value = config.collect_insert_target ?? 200;
  $("autoValidateTarget").value = config.validate_valid_target ?? 20;
  $("autoCheckIntervalMinutes").value = config.check_interval_minutes ?? 5;
  $("autoCollectorWorkers").value = config.collector_workers ?? 5;
  $("autoCollectorDepth").value = config.collector_depth ?? 8;
  $("autoCollectorDelay").value = config.collector_delay ?? 1;
  $("autoCollectorJitter").value = config.collector_jitter ?? 0.5;
  $("autoCollectorLogLevel").value = config.collector_log_level || "detail";
  $("autoValidatorWorkers").value = config.validator_workers ?? 10;
  $("autoValidatorRounds").value = config.validator_rounds ?? 3;
  $("autoValidatorTimeout").value = config.validator_timeout ?? 8;
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
  };
}

function refreshSubscriptionUrl() {
  $("subscriptionUrl").value = `${window.location.origin}${BASE_PATH}/api/subscription/base64`;
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
    $("connectionDot").classList.add("online");
    $("connectionText").textContent = "本地服务在线";
    $("totalNodes").textContent = data.database.total_nodes;
    $("validNodes").textContent = data.database.valid_nodes;
    $("pendingNodes").textContent = data.database.statuses["未验证"] || 0;
    $("invalidNodes").textContent = data.database.statuses["无效"] || 0;
    $("duplicateNodes").textContent = data.database.duplicate_filtered || 0;
    $("repoCount").textContent = `${data.repos?.count || 0} 个仓库`;
    const collectorRunning = data.tasks.collector.running;
    const validatorRunning = data.tasks.validator.running;
    const botRunning = data.tasks.bot?.running || false;
    taskBadge("collectorBadge", collectorRunning);
    taskBadge("validatorBadge", validatorRunning);
    taskBadge("botBadge", botRunning);
    $("startCollector").disabled = collectorRunning || validatorRunning;
    $("stopCollector").disabled = !data.tasks.collector.running;
    $("startValidator").disabled = validatorRunning || collectorRunning;
    $("stopValidator").disabled = !data.tasks.validator.running;
    const auto = data.auto || {};
    $("autoBadge").textContent = auto.enabled ? "已开启" : "已关闭";
    $("autoBadge").classList.toggle("running", !!auto.enabled);
    $("autoPhase").textContent = phaseText(auto.phase);
    $("autoReason").textContent = auto.last_reason || "等待状态同步";
    $("autoNotice").textContent = autoNoticeText(auto, data.database);
    $("autoValidCount").textContent = data.database.valid_nodes;
    $("autoLowWatermarkView").textContent = auto.config?.valid_low_watermark ?? 0;
    $("autoPendingCount").textContent = data.database.total_nodes;
    $("autoCollectProgress").textContent = `${auto.collect?.current ?? 0} / ${auto.collect?.target ?? 0}`;
    $("autoValidateProgress").textContent = `${auto.validate?.current ?? 0} / ${auto.validate?.target ?? 0}`;
    $("autoCollectorState").textContent = collectorRunning ? "采集运行中" : "采集已停止";
    $("autoValidatorState").textContent = validatorRunning ? "验证运行中" : "验证已停止";
    setLight("autoLight", !!auto.enabled, auto.phase === "error");
    setLight("autoCollectorLight", collectorRunning);
    setLight("autoValidatorLight", validatorRunning);
    $("startAuto").disabled = !!auto.enabled;
    $("stopAuto").disabled = !auto.enabled && !collectorRunning && !validatorRunning;
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
  $("botPublicBaseUrl").value = config.public_base_url || "";
  $("botAutoRun").checked = !!config.auto_run;
  $("botKeywords").value = config.keywords || "";
  $("botReplyMessage").value = config.reply_message || "";
}

function botPayload() {
  return {
    bot_token: $("botToken").value,
    bot_username: $("botUsername").value,
    public_base_url: $("botPublicBaseUrl").value,
    auto_run: $("botAutoRun").checked,
    keywords: $("botKeywords").value,
    reply_message: $("botReplyMessage").value,
  };
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
    $("botMessages").innerHTML = (data.messages || []).length ? data.messages.map((item) => `
      <article class="profile-card">
        <div class="node-meta"><span class="protocol">${escapeHtml(item.direction)}</span><span>${escapeHtml(item.created_at || "")}</span><span>用户 ${escapeHtml(item.telegram_user_id || "未知")}</span></div>
        <div class="node-uri">${escapeHtml(item.message || "")}</div>
      </article>`).join("") : `<p class="hint">暂无 BOT 消息记录。</p>`;
  } catch (error) {
    toast(error.message);
  }
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

async function refreshRepos() {
  try {
    const data = await jsonFetch(api("/api/repos"));
    $("repoList").value = (data.repos || []).join("\n");
    $("repoCount").textContent = `${data.count || 0} 个仓库`;
  } catch (error) {
    toast(error.message);
  }
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

function renderLogs() {
  const visible = logEvents.filter((event) => logFilter === "all" || event.source === logFilter);
  $("logs").textContent = visible.map((event) => `[${event.time}] [${event.source}] ${event.message}`).join("\n");
  $("logs").scrollTop = $("logs").scrollHeight;
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

async function refreshNodes() {
  try {
    const protocol = encodeURIComponent($("validProtocol").value);
    const country = encodeURIComponent($("validCountry").value);
    const data = await jsonFetch(api(`/api/valid-nodes?page=${page}&limit=${nodePageSize}&protocol=${protocol}&country=${country}`));
    nodeTotal = data.total;
    $("pageText").textContent = `第 ${page} 页 · 共 ${nodeTotal} 条`;
    $("previousPage").disabled = page <= 1;
    $("nextPage").disabled = page * data.limit >= nodeTotal;
    updateSelectOptions("validProtocol", data.protocols || [], "全部协议");
    updateSelectOptions("validCountry", data.countries || [], "全部国家");
    $("nodeList").innerHTML = data.nodes.length ? data.nodes.map((node) => `
      <article class="node-card">
        <div class="node-meta"><span class="protocol">${node.protocol}</span><span>国家 ${node.country || "未知"}</span><span>出口 ${node.proxy_ips || "未知"}</span><span>${Number(node.seconds).toFixed(2)} 秒</span></div>
        <div class="node-uri">${escapeHtml(node.uri)}</div>
      </article>`).join("") : `<p class="hint">暂无有效节点。启动验证后，通过稳定检查的节点会出现在这里。</p>`;
  } catch (error) {
    toast(error.message);
  }
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

function subscriptionPayload() {
  return {
    name: $("subscriptionName").value,
    mode: $("subscriptionMode").value,
    max_uses: $("subscriptionMaxUses").value,
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
    toast("订阅链接已生成");
    try {
      await navigator.clipboard?.writeText(data.subscription?.url || "");
    } catch (error) {
      // Clipboard permissions vary by browser; creation itself has already succeeded.
    }
    await refreshSubscriptions();
  } catch (error) {
    toast(error.message);
  }
}

function renderSubscriptions(items) {
  $("subscriptionList").innerHTML = items.length ? items.map((item) => `
    <article class="subscription-card">
      <div class="node-meta">
        <span class="protocol">${escapeHtml(item.status)}</span>
        <span>${item.mode === "usage" ? "按次数" : item.mode === "time" ? "按时间" : "次数或时间"}</span>
        <span>已用 ${item.used_count || 0}${item.max_uses ? " / " + item.max_uses : ""}</span>
        <span>过期 ${escapeHtml(item.expires_at || "不按时间")}</span>
        <span>最后访问 ${escapeHtml(item.last_used_at || "未访问")}</span>
      </div>
      <div class="node-name">${escapeHtml(item.name || "")}</div>
      <div class="node-uri">${escapeHtml(item.url || "")}</div>
      <div class="node-meta">${escapeHtml(item.remark || "无备注")}</div>
      <div class="actions compact-actions">
        <button class="ghost" data-copy-subscription="${escapeHtml(item.url || "")}">复制链接</button>
        <button class="ghost" data-toggle-subscription="${escapeHtml(item.token)}" data-enabled="${item.enabled ? "0" : "1"}">${item.enabled ? "禁用" : "启用"}</button>
        <button class="danger" data-delete-subscription="${escapeHtml(item.token)}">删除</button>
      </div>
    </article>
  `).join("") : `<p class="hint">暂无订阅链接。生成后会显示在这里。</p>`;
  bindSubscriptionActions();
}

function bindSubscriptionActions() {
  document.querySelectorAll("[data-copy-subscription]").forEach((button) => {
    button.onclick = async () => {
      await navigator.clipboard.writeText(button.dataset.copySubscription || "");
      toast("订阅链接已复制");
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

function toDateTimeLocal(value) {
  if (!value) return "";
  return String(value).replace(" ", "T").slice(0, 16);
}

function applyClaimConfig(config = {}) {
  $("claimYoutubeChannelUrl").value = config.youtube_channel_url || "";
  $("claimCode").value = config.claim_code || "";
  $("claimVersion").value = config.claim_version || "";
  $("claimExpiresAt").value = toDateTimeLocal(config.claim_expires_at || "");
  $("claimDailyLimit").value = config.daily_claim_limit || 1;
  $("claimGroupDmSuccess").value = config.group_dm_success_message || "";
  $("claimGroupDmFailed").value = config.group_dm_failed_message || "";
  $("claimPromptMessage").value = config.claim_prompt_message || "";
  $("claimYoutubeButtonMessage").value = config.youtube_button_message || "";
  $("claimAskCodeMessage").value = config.ask_code_message || "";
  $("claimWrongCodeMessage").value = config.wrong_code_message || "";
  $("claimExpiredCodeMessage").value = config.expired_code_message || "";
  $("claimLimitMessage").value = config.limit_message || "";
  $("claimSuccessMessage").value = config.success_message || "";
  $("claimVersionNotice").textContent = `当前口令版本：${config.claim_version || "未设置"}。新生成的订阅链接会绑定此版本，后续更换版本后旧链接将失效。`;
}

function claimConfigPayload() {
  return {
    youtube_channel_url: $("claimYoutubeChannelUrl").value,
    claim_code: $("claimCode").value,
    claim_version: $("claimVersion").value,
    claim_expires_at: $("claimExpiresAt").value,
    daily_claim_limit: $("claimDailyLimit").value,
    group_dm_success_message: $("claimGroupDmSuccess").value,
    group_dm_failed_message: $("claimGroupDmFailed").value,
    claim_prompt_message: $("claimPromptMessage").value,
    youtube_button_message: $("claimYoutubeButtonMessage").value,
    ask_code_message: $("claimAskCodeMessage").value,
    wrong_code_message: $("claimWrongCodeMessage").value,
    expired_code_message: $("claimExpiredCodeMessage").value,
    limit_message: $("claimLimitMessage").value,
    success_message: $("claimSuccessMessage").value,
  };
}

async function refreshClaimConfig() {
  try {
    const data = await jsonFetch(api("/api/claim-code/config"));
    applyClaimConfig(data.config || {});
  } catch (error) {
    toast(error.message);
  }
}

async function saveClaimConfig() {
  try {
    const data = await jsonFetch(api("/api/claim-code/config"), {
      method: "POST",
      body: JSON.stringify(claimConfigPayload()),
    });
    applyClaimConfig(data.config || {});
    toast("领取口令配置已保存");
    await refreshSubscriptions();
  } catch (error) {
    toast(error.message);
  }
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

async function exportSubscription() {
  try {
    const data = await jsonFetch(api("/api/node-processing/export"), {
      method: "POST",
      body: JSON.stringify({ rename_template: $("renameTemplate").value }),
    });
    $("subscriptionOutput").value = data.subscription || "";
    $("exportSummary").textContent = `已生成 Base64 订阅：${data.count || 0} 个有效节点，原始订阅字节 ${data.plain_bytes || 0}。数据库原始节点未修改。`;
    toast("Base64 订阅已生成");
  } catch (error) {
    toast(error.message);
  }
}

async function copySubscription() {
  const value = $("subscriptionOutput").value;
  if (!value) {
    toast("请先生成 Base64 订阅");
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    toast("订阅内容已复制");
  } catch (error) {
    $("subscriptionOutput").select();
    document.execCommand("copy");
    toast("订阅内容已复制");
  }
}

async function copySubscriptionUrl() {
  const value = $("subscriptionUrl").value;
  try {
    await navigator.clipboard.writeText(value);
    toast("订阅地址已复制");
  } catch (error) {
    $("subscriptionUrl").select();
    document.execCommand("copy");
    toast("订阅地址已复制");
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
  const pending = database.total_nodes || 0;
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
$("saveRepos").onclick = async () => {
  const repos = $("repoList").value.split(/\r?\n/);
  try {
    const data = await jsonFetch(api("/api/repos"), { method: "POST", body: JSON.stringify({ repos }) });
    $("repoList").value = data.repos.join("\n");
    $("repoCount").textContent = `${data.count} 个仓库`;
    toast("仓库画像已保存");
  } catch (error) {
    toast(error.message);
  }
};
$("resetRepos").onclick = async () => {
  try {
    const data = await jsonFetch(api("/api/repos/reset"), { method: "POST", body: "{}" });
    $("repoList").value = data.repos.join("\n");
    $("repoCount").textContent = `${data.count} 个仓库`;
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
$("refreshProfiles").onclick = refreshProfiles;
$("refreshProcessingPreview").onclick = previewRenameTemplate;
$("saveRenameTemplate").onclick = saveRenameTemplate;
$("previewRenameTemplate").onclick = previewRenameTemplate;
$("exportSubscription").onclick = exportSubscription;
$("copySubscriptionUrl").onclick = copySubscriptionUrl;
$("copySubscription").onclick = copySubscription;
$("refreshSubscriptions").onclick = refreshSubscriptions;
$("createSubscription").onclick = createSubscription;
$("refreshClaimConfig").onclick = refreshClaimConfig;
$("saveClaimConfig").onclick = saveClaimConfig;
$("saveBotConfig").onclick = saveBotConfig;
$("startBot").onclick = () => post(api("/api/bot/start")).then(refreshBot);
$("stopBot").onclick = () => post(api("/api/bot/stop")).then(refreshBot);
$("disableBot").onclick = () => post(api("/api/bot/disable")).then(refreshBot);
$("refreshBot").onclick = refreshBot;
$("subscriptionMode").onchange = updateSubscriptionMode;
$("logoutButton").onclick = logout;
$("accountButton").onclick = () => $("accountDialog").showModal();
$("closeAccount").onclick = () => $("accountDialog").close();
$("saveAccount").onclick = saveAccount;
$("previousPage").onclick = () => { if (page > 1) { page -= 1; refreshNodes(); } };
$("nextPage").onclick = () => { if (page * nodePageSize < nodeTotal) { page += 1; refreshNodes(); } };
$("validProtocol").onchange = () => { page = 1; refreshNodes(); };
$("validCountry").onchange = () => { page = 1; refreshNodes(); };
document.querySelectorAll(".tab").forEach((button) => button.onclick = () => {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
  button.classList.add("active");
  logFilter = button.dataset.logSource;
  renderLogs();
});
document.querySelectorAll(".page-tab").forEach((button) => button.onclick = () => {
  document.querySelectorAll(".page-tab").forEach((tab) => tab.classList.remove("active"));
  document.querySelectorAll(".page").forEach((pageElement) => pageElement.classList.remove("active"));
  button.classList.add("active");
  $(button.dataset.page).classList.add("active");
});

async function startDashboard() {
  refreshStatus.autoConfigLoaded = false;
  await Promise.all([
    refreshStatus(),
    refreshRepos(),
    refreshProfiles(),
    refreshNodes(),
    refreshProcessingConfig(),
    refreshProcessingPreview(),
    refreshSubscriptions(),
    refreshClaimConfig(),
    refreshBot(),
  ]);
  refreshSubscriptionUrl();
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
  }
}, 3000);
