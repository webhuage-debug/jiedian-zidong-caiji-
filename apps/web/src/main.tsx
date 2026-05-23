import React from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  BarChart3,
  Database,
  Download,
  Eye,
  EyeOff,
  FileArchive,
  Gauge,
  GitBranch,
  Home,
  Link2,
  ListFilter,
  LogOut,
  MessageSquare,
  Play,
  ScrollText,
  Settings,
  ShieldCheck,
  Video
} from "lucide-react";
import "./styles.css";

type AuthStatus = {
  authenticated: boolean;
  user?: { id: number; username: string } | null;
};

type Summary = {
  version: string;
  systemStatus: string;
  candidateNodes: number;
  pendingNodes: number;
  failedNodes: number;
  collectedNodes: number;
  publishedBatches: number;
  latencyDistribution: Array<{ label: string; count: number }>;
};

type CollectionRun = {
  id: number;
  status: string;
  discovered_sources: number;
  fetched_sources: number;
  raw_nodes: number;
  inserted_nodes: number;
  error_count: number;
};

type TestRun = {
  id: number;
  status: string;
  tested_nodes: number;
  passed_nodes: number;
  failed_nodes: number;
  avg_latency_ms?: number;
};

type NodeItem = {
  id: number;
  protocol: string;
  source_url?: string;
  source_type?: string;
  collected_at?: string;
  last_tested_at?: string;
  latency_ms?: number;
  status: string;
  failure_reason?: string;
  exported_at?: string;
  export_batch_id?: number;
};

type ExportBatch = {
  id: number;
  batch_code: string;
  name: string;
  status: string;
  node_count: number;
  public_slug: string;
};

type SourceItem = {
  id: number;
  url: string;
  source_type: string;
  status: string;
  success_count: number;
  failure_count: number;
  last_error?: string;
};

type BatchStat = {
  id: number;
  batch_code: string;
  name: string;
  status: string;
  node_count: number;
  public_slug: string;
  view_count?: number;
  passphrase_attempt_count?: number;
  passphrase_correct_count?: number;
  passphrase_wrong_count?: number;
  unlock_count?: number;
  download_count?: number;
  feedback_count?: number;
};

type FeedbackItem = {
  id: number;
  batch_code?: string;
  region?: string;
  carrier?: string;
  device?: string;
  client_app?: string;
  is_usable?: number | null;
  note?: string;
  created_at?: string;
};

type LogItem = {
  level: string;
  message: string;
  created_at: string;
};

type PublicBatch = {
  name: string;
  description: string;
  expiresAt?: string | null;
  createdAt: string;
};

type ViewKey =
  | "dashboard"
  | "nodes"
  | "collection"
  | "tests"
  | "failed"
  | "packages"
  | "claim"
  | "stats"
  | "feedback"
  | "settings"
  | "logs";

const navItems: Array<{ key: ViewKey; label: string; icon: React.ReactNode }> = [
  { key: "dashboard", label: "首页仪表盘", icon: <Home size={17} /> },
  { key: "nodes", label: "节点池", icon: <Database size={17} /> },
  { key: "collection", label: "采集任务", icon: <GitBranch size={17} /> },
  { key: "tests", label: "测试记录", icon: <Activity size={17} /> },
  { key: "failed", label: "失效节点记录", icon: <ListFilter size={17} /> },
  { key: "packages", label: "节点包管理", icon: <FileArchive size={17} /> },
  { key: "claim", label: "领取页管理", icon: <Link2 size={17} /> },
  { key: "stats", label: "统计数据", icon: <BarChart3 size={17} /> },
  { key: "feedback", label: "反馈数据", icon: <MessageSquare size={17} /> },
  { key: "settings", label: "系统设置", icon: <Settings size={17} /> },
  { key: "logs", label: "运行日志", icon: <ScrollText size={17} /> }
];

function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  return fetch(input, {
    credentials: "same-origin",
    ...init
  });
}

function App() {
  const publicMatch = window.location.pathname.match(/^\/p\/([^/]+)/);
  if (publicMatch) return <PublicClaimPage slug={publicMatch[1]} />;
  return <AdminApp />;
}

function AdminApp() {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);

  React.useEffect(() => {
    apiFetch("/api/auth/status")
      .then((res) => res.json())
      .then(setAuth)
      .catch(() => setAuth({ authenticated: false }));
  }, []);

  if (!auth) return <div className="boot">正在检查登录状态...</div>;
  if (!auth.authenticated) return <Login onLogin={setAuth} />;
  return <Dashboard user={auth.user!} onLogout={() => setAuth({ authenticated: false })} />;
}

function Login({ onLogin }: { onLogin: (auth: AuthStatus) => void }) {
  const [username, setUsername] = React.useState("admin");
  const [password, setPassword] = React.useState("");
  const [visible, setVisible] = React.useState(false);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const res = await apiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    setLoading(false);
    if (!res.ok) {
      setError(data.message ?? "登录失败");
      return;
    }
    onLogin({ authenticated: true, user: data.user });
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div className="brand-row">
          <ShieldCheck size={30} />
          <div>
            <h1>Public Node Admin</h1>
            <p>个人 VPS 公开节点采集后台</p>
          </div>
        </div>
        <form onSubmit={submit} className="login-form">
          <label>
            管理员账号
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            登录密码
            <div className="password-box">
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type={visible ? "text" : "password"}
                autoComplete="current-password"
              />
              <button type="button" aria-label={visible ? "隐藏密码" : "显示密码"} onClick={() => setVisible((value) => !value)}>
                {visible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>
          {error && <div className="error">{error}</div>}
          <button className="primary" disabled={loading}>{loading ? "登录中..." : "登录后台"}</button>
        </form>
      </section>
    </main>
  );
}

function Dashboard({ user, onLogout }: { user: { username: string }; onLogout: () => void }) {
  const [activeView, setActiveView] = React.useState<ViewKey>("dashboard");
  const [summary, setSummary] = React.useState<Summary | null>(null);
  const [sources, setSources] = React.useState<SourceItem[]>([]);
  const [runs, setRuns] = React.useState<CollectionRun[]>([]);
  const [testRuns, setTestRuns] = React.useState<TestRun[]>([]);
  const [nodes, setNodes] = React.useState<NodeItem[]>([]);
  const [failedNodes, setFailedNodes] = React.useState<NodeItem[]>([]);
  const [batches, setBatches] = React.useState<ExportBatch[]>([]);
  const [stats, setStats] = React.useState<BatchStat[]>([]);
  const [feedback, setFeedback] = React.useState<FeedbackItem[]>([]);
  const [logs, setLogs] = React.useState<LogItem[]>([]);
  const [videoMode, setVideoMode] = React.useState(false);
  const [collecting, setCollecting] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [exporting, setExporting] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [nodeFilters, setNodeFilters] = React.useState({
    protocol: "",
    status: "test_passed",
    maxLatency: "",
    exported: ""
  });
  const [exportForm, setExportForm] = React.useState({
    name: "本期候选节点",
    count: 10,
    maxLatencyMs: "",
    passphrase: "",
    publish: true
  });

  const refresh = React.useCallback(async () => {
    const nodeQuery = new URLSearchParams({ limit: "50" });
    if (nodeFilters.protocol) nodeQuery.set("protocol", nodeFilters.protocol);
    if (nodeFilters.status) nodeQuery.set("status", nodeFilters.status);
    if (nodeFilters.maxLatency) nodeQuery.set("maxLatency", nodeFilters.maxLatency);
    if (nodeFilters.exported) nodeQuery.set("exported", nodeFilters.exported);

    const [
      summaryRes,
      sourcesRes,
      runsRes,
      testRunsRes,
      nodesRes,
      failedNodesRes,
      batchesRes,
      videoModeRes,
      statsRes,
      feedbackRes,
      logsRes
    ] = await Promise.all([
      apiFetch("/api/dashboard/summary"),
      apiFetch("/api/sources"),
      apiFetch("/api/collection-runs"),
      apiFetch("/api/test-runs"),
      apiFetch(`/api/nodes?${nodeQuery.toString()}`),
      apiFetch("/api/nodes?status=test_failed&limit=50"),
      apiFetch("/api/export-batches"),
      apiFetch("/api/settings/video-mode"),
      apiFetch("/api/stats/batches"),
      apiFetch("/api/feedback"),
      apiFetch("/api/logs")
    ]);
    setSummary(await summaryRes.json());
    setSources((await sourcesRes.json()).items ?? []);
    setRuns((await runsRes.json()).items ?? []);
    setTestRuns((await testRunsRes.json()).items ?? []);
    setNodes((await nodesRes.json()).items ?? []);
    setFailedNodes((await failedNodesRes.json()).items ?? []);
    setBatches((await batchesRes.json()).items ?? []);
    setVideoMode(Boolean((await videoModeRes.json()).enabled));
    setStats((await statsRes.json()).items ?? []);
    setFeedback((await feedbackRes.json()).items ?? []);
    setLogs((await logsRes.json()).items ?? []);
  }, [nodeFilters]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  async function logout() {
    await apiFetch("/api/auth/logout", { method: "POST" });
    onLogout();
  }

  async function runCollector() {
    setCollecting(true);
    setNotice("采集任务已开始，系统会限速抓取公开 URL...");
    const res = await apiFetch("/api/collection-runs", { method: "POST" });
    const data = await res.json();
    setCollecting(false);
    if (!res.ok) {
      setNotice(data.message ?? "采集失败");
      return;
    }
    setNotice(`本次采集原始节点 ${data.summary.rawNodes} 条，新增入库 ${data.summary.insertedNodes} 条。`);
    await refresh();
  }

  async function runTester() {
    setTesting(true);
    setNotice("基础测试已开始，正在并发测试前 100 条待测试节点，请稍候...");
    const res = await apiFetch("/api/test-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 100 })
    });
    const data = await res.json();
    setTesting(false);
    if (!res.ok) {
      setNotice(data.message ?? "测试失败");
      return;
    }
    setNotice(`本次测试 ${data.summary.testedNodes} 条，通过 ${data.summary.passedNodes} 条，失败剔除 ${data.summary.failedNodes} 条。`);
    await refresh();
  }

  async function createExport(event: React.FormEvent) {
    event.preventDefault();
    if (!exportForm.passphrase.trim()) {
      setNotice("请先填写本期口令，口令会同时用于领取页验证和 zip 解压。");
      return;
    }
    setExporting(true);
    setNotice("正在生成节点包...");
    const res = await apiFetch("/api/export-batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: exportForm.name,
        count: Number(exportForm.count),
        maxLatencyMs: exportForm.maxLatencyMs ? Number(exportForm.maxLatencyMs) : undefined,
        passphrase: exportForm.passphrase,
        publish: exportForm.publish,
        sort: "latency_asc",
        includeExported: false
      })
    });
    const data = await res.json();
    setExporting(false);
    if (!res.ok) {
      setNotice(data.message === "no eligible nodes for export" ? "没有符合条件的已通过节点，请先运行基础测试或放宽最大延迟。" : data.message ?? "导出失败");
      return;
    }
    setNotice(`节点包已生成：${data.batch.batchCode}，数量 ${data.batch.nodeCount} 条。`);
    setActiveView("packages");
    setExportForm((value) => ({ ...value, passphrase: "" }));
    await refresh();
  }

  async function toggleVideoMode() {
    const next = !videoMode;
    await apiFetch("/api/settings/video-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: next })
    });
    await refresh();
  }

  const currentNav = navItems.find((item) => item.key === activeView) ?? navItems[0];
  const displayUser = videoMode ? "已隐藏" : user.username;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-title"><Gauge size={24} /> 管理后台</div>
        <nav aria-label="后台菜单">
          {navItems.map((item) => (
            <button
              key={item.key}
              className={item.key === activeView ? "nav active" : "nav"}
              onClick={() => setActiveView(item.key)}
              type="button"
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>
      </aside>
      <section className="content">
        <header className="topbar">
          <div>
            <h1>{currentNav.label}</h1>
            <p>v1.0.0 正式版：采集、测试、导出、领取、反馈、统计和安全模式。</p>
          </div>
          <div className="top-actions">
            <button className={videoMode ? "icon active" : "icon"} onClick={toggleVideoMode} title="公开视频模式">
              <Video size={18} />
              公开视频模式
            </button>
            <span className="user">管理员：{displayUser}</span>
            <button className="icon" onClick={logout}><LogOut size={18} /> 退出</button>
          </div>
        </header>

        {notice && <div className="notice">{notice}</div>}

        {activeView === "dashboard" && (
          <>
            <Metrics summary={summary} />
            <LatencyDistribution summary={summary} />
            <NodePreview title="低延迟候选节点预览" nodes={nodes.slice(0, 8)} />
            <BatchTable batches={batches} compact />
          </>
        )}

        {activeView === "nodes" && (
          <NodesPanel
            nodes={nodes}
            filters={nodeFilters}
            onFiltersChange={setNodeFilters}
            onRefresh={refresh}
          />
        )}

        {activeView === "collection" && (
          <CollectionPanel runs={runs} sources={sources} videoMode={videoMode} collecting={collecting} onRun={runCollector} />
        )}

        {activeView === "tests" && (
          <TestPanel runs={testRuns} testing={testing} onRun={runTester} />
        )}

        {activeView === "failed" && (
          <NodePreview title="失效节点记录" nodes={failedNodes} />
        )}

        {activeView === "packages" && (
          <ExportPanel form={exportForm} setForm={setExportForm} exporting={exporting} onSubmit={createExport} batches={batches} />
        )}

        {activeView === "claim" && (
          <ClaimPanel batches={batches} />
        )}

        {activeView === "stats" && (
          <StatsPanel stats={stats} />
        )}

        {activeView === "feedback" && (
          <FeedbackPanel feedback={feedback} />
        )}

        {activeView === "settings" && (
          <SettingsPanel videoMode={videoMode} onToggleVideoMode={toggleVideoMode} summary={summary} />
        )}

        {activeView === "logs" && (
          <LogsPanel logs={logs} />
        )}
      </section>
    </main>
  );
}

function Metrics({ summary }: { summary: Summary | null }) {
  return (
    <section className="metrics">
      <Metric label="已采集节点" value={summary?.collectedNodes ?? 0} />
      <Metric label="待测试节点" value={summary?.pendingNodes ?? 0} />
      <Metric label="候选节点" value={summary?.candidateNodes ?? 0} />
      <Metric label="失败/剔除" value={summary?.failedNodes ?? 0} />
    </section>
  );
}

function NodesPanel({
  nodes,
  filters,
  onFiltersChange,
  onRefresh
}: {
  nodes: NodeItem[];
  filters: { protocol: string; status: string; maxLatency: string; exported: string };
  onFiltersChange: React.Dispatch<React.SetStateAction<{ protocol: string; status: string; maxLatency: string; exported: string }>>;
  onRefresh: () => void;
}) {
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>候选节点池</h2>
          <p className="muted compact">默认只显示基础测试通过的节点，可以按协议、状态、延迟和导出状态筛选。</p>
        </div>
        <button className="primary small" onClick={onRefresh} type="button">刷新</button>
      </div>
      <div className="filter-form">
        <label>
          协议
          <select value={filters.protocol} onChange={(event) => onFiltersChange((value) => ({ ...value, protocol: event.target.value }))}>
            <option value="">全部</option>
            <option value="vmess">vmess</option>
            <option value="vless">vless</option>
            <option value="trojan">trojan</option>
            <option value="ss">ss</option>
            <option value="ssr">ssr</option>
            <option value="hysteria2">hysteria2</option>
            <option value="hy2">hy2</option>
            <option value="tuic">tuic</option>
          </select>
        </label>
        <label>
          状态
          <select value={filters.status} onChange={(event) => onFiltersChange((value) => ({ ...value, status: event.target.value }))}>
            <option value="test_passed">测试通过</option>
            <option value="pending_test">待测试</option>
            <option value="test_failed">测试失败</option>
            <option value="exported">已导出</option>
            <option value="">全部</option>
          </select>
        </label>
        <label>
          最大延迟 ms
          <input value={filters.maxLatency} placeholder="例如 300" onChange={(event) => onFiltersChange((value) => ({ ...value, maxLatency: event.target.value }))} />
        </label>
        <label>
          导出状态
          <select value={filters.exported} onChange={(event) => onFiltersChange((value) => ({ ...value, exported: event.target.value }))}>
            <option value="">全部</option>
            <option value="false">未导出</option>
            <option value="true">已导出</option>
          </select>
        </label>
      </div>
      <NodeTable nodes={nodes} />
    </section>
  );
}

function CollectionPanel({
  runs,
  sources,
  videoMode,
  collecting,
  onRun
}: {
  runs: CollectionRun[];
  sources: SourceItem[];
  videoMode: boolean;
  collecting: boolean;
  onRun: () => void;
}) {
  return (
    <>
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>采集任务</h2>
            <p className="muted compact">采集任务已限制频率和并发，只抓取公开 URL。</p>
          </div>
          <button className="primary small" onClick={onRun} disabled={collecting}>
            <Play size={16} />
            {collecting ? "采集中..." : "开始采集"}
          </button>
        </div>
        <RunTable runs={runs} />
      </section>
      <SourceCache sources={sources} videoMode={videoMode} />
    </>
  );
}

function TestPanel({ runs, testing, onRun }: { runs: TestRun[]; testing: boolean; onRun: () => void }) {
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>基础测试</h2>
          <p className="muted compact">只做后台初筛 TCP 连通性测试，失败节点不进入候选池。</p>
        </div>
        <button className="primary small" onClick={onRun} disabled={testing}>
          <Activity size={16} />
          {testing ? "测试中..." : "开始测试"}
        </button>
      </div>
      <TestRunTable runs={runs} />
    </section>
  );
}

function ExportPanel({
  form,
  setForm,
  exporting,
  onSubmit,
  batches
}: {
  form: { name: string; count: number; maxLatencyMs: string; passphrase: string; publish: boolean };
  setForm: React.Dispatch<React.SetStateAction<{ name: string; count: number; maxLatencyMs: string; passphrase: string; publish: boolean }>>;
  exporting: boolean;
  onSubmit: (event: React.FormEvent) => void;
  batches: ExportBatch[];
}) {
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>节点包导出</h2>
          <p className="muted compact">默认导出 10 条，可手动改成 11、20、30 或自定义数量。导出优先选择测试通过且延迟最低的节点。</p>
        </div>
      </div>
      <form className="export-form" onSubmit={onSubmit}>
        <label>
          批次名称
          <input value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} />
        </label>
        <label>
          导出数量
          <input type="number" min="1" max="1000" value={form.count} onChange={(event) => setForm((value) => ({ ...value, count: Number(event.target.value) }))} />
        </label>
        <label>
          最大延迟 ms
          <input placeholder="例如 300" value={form.maxLatencyMs} onChange={(event) => setForm((value) => ({ ...value, maxLatencyMs: event.target.value }))} />
        </label>
        <label>
          本期口令
          <input type="password" value={form.passphrase} onChange={(event) => setForm((value) => ({ ...value, passphrase: event.target.value }))} required />
        </label>
        <label className="check-row">
          <input type="checkbox" checked={form.publish} onChange={(event) => setForm((value) => ({ ...value, publish: event.target.checked }))} />
          发布领取页
        </label>
        <button className="primary small" disabled={exporting}>
          <FileArchive size={16} />
          {exporting ? "生成中..." : "生成节点包"}
        </button>
      </form>
      <BatchTable batches={batches} />
    </section>
  );
}

function ClaimPanel({ batches }: { batches: ExportBatch[] }) {
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>领取页管理</h2>
          <p className="muted compact">点击领取页可以直接打开公开页面。外部用户输入正确口令后才能下载加密 zip 节点包。</p>
        </div>
      </div>
      <BatchTable batches={batches} claimOnly />
    </section>
  );
}

function StatsPanel({ stats }: { stats: BatchStat[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>领取统计</h2><BarChart3 size={18} /></div>
      <div className="table">
        <div className="table-head stats-grid"><span>批次</span><span>访问</span><span>口令输入</span><span>正确</span><span>错误</span><span>下载</span><span>反馈</span></div>
        {stats.map((item) => (
          <div className="table-row stats-grid" key={item.id}>
            <span>{item.batch_code}</span>
            <span>{item.view_count ?? 0}</span>
            <span>{item.passphrase_attempt_count ?? 0}</span>
            <span>{item.passphrase_correct_count ?? 0}</span>
            <span>{item.passphrase_wrong_count ?? 0}</span>
            <span>{item.download_count ?? 0}</span>
            <span>{item.feedback_count ?? 0}</span>
          </div>
        ))}
        {!stats.length && <p className="muted">暂无统计数据。</p>}
      </div>
    </section>
  );
}

function FeedbackPanel({ feedback }: { feedback: FeedbackItem[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>反馈数据</h2><MessageSquare size={18} /></div>
      <div className="table">
        <div className="table-head feedback-grid"><span>批次</span><span>地区</span><span>运营商</span><span>设备</span><span>软件</span><span>可用</span><span>备注</span></div>
        {feedback.map((item) => (
          <div className="table-row feedback-grid" key={item.id}>
            <span>{item.batch_code ?? "-"}</span>
            <span>{item.region || "-"}</span>
            <span>{item.carrier || "-"}</span>
            <span>{item.device || "-"}</span>
            <span>{item.client_app || "-"}</span>
            <span>{item.is_usable === null || item.is_usable === undefined ? "-" : item.is_usable ? "是" : "否"}</span>
            <span className="truncate">{item.note || "-"}</span>
          </div>
        ))}
        {!feedback.length && <p className="muted">暂无反馈。</p>}
      </div>
    </section>
  );
}

function SettingsPanel({ videoMode, onToggleVideoMode, summary }: { videoMode: boolean; onToggleVideoMode: () => void; summary: Summary | null }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>系统设置</h2><Settings size={18} /></div>
      <div className="settings-grid">
        <div>
          <strong>公开视频模式</strong>
          <p className="muted compact">开启后隐藏管理员账号、完整节点、来源链接、Token、IP、UUID、密码等敏感信息。</p>
        </div>
        <button className={videoMode ? "primary small" : "icon"} onClick={onToggleVideoMode} type="button">
          {videoMode ? "已开启" : "开启"}
        </button>
        <div>
          <strong>系统状态</strong>
          <p className="muted compact">{summary?.systemStatus ?? "running"} / v{summary?.version ?? "1.0.0"}</p>
        </div>
      </div>
    </section>
  );
}

function LogsPanel({ logs }: { logs: LogItem[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>运行日志</h2><ScrollText size={18} /></div>
      <div className="table">
        <div className="table-head log-grid"><span>时间</span><span>级别</span><span>内容</span></div>
        {logs.map((log, index) => (
          <div className="table-row log-grid" key={`${log.created_at}-${index}`}>
            <span>{formatDate(log.created_at)}</span>
            <span>{log.level}</span>
            <span className="truncate">{log.message}</span>
          </div>
        ))}
        {!logs.length && <p className="muted">暂无运行日志。</p>}
      </div>
    </section>
  );
}

function PublicClaimPage({ slug }: { slug: string }) {
  const [batch, setBatch] = React.useState<PublicBatch | null>(null);
  const [found, setFound] = React.useState(true);
  const [unlocked, setUnlocked] = React.useState(false);
  const [passphrase, setPassphrase] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [feedback, setFeedback] = React.useState({
    region: "",
    carrier: "",
    device: "",
    clientApp: "",
    isUsable: true,
    note: ""
  });

  React.useEffect(() => {
    apiFetch(`/api/public/batches/${slug}${window.location.search}`)
      .then((res) => res.json())
      .then((data) => {
        setFound(data.found);
        setBatch(data.batch ?? null);
        setUnlocked(Boolean(data.unlocked));
      })
      .catch(() => setFound(false));
  }, [slug]);

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    const res = await apiFetch(`/api/public/batches/${slug}/verify${window.location.search}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase })
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage(data.message ?? "口令验证失败");
      return;
    }
    setUnlocked(true);
    setMessage("口令正确，可以下载节点包。zip 解压密码就是本期口令。");
  }

  async function submitFeedback(event: React.FormEvent) {
    event.preventDefault();
    const res = await apiFetch(`/api/public/batches/${slug}/feedback${window.location.search}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(feedback)
    });
    setMessage(res.ok ? "反馈已提交，谢谢。" : "反馈提交失败。");
  }

  if (!found) {
    return <main className="public-shell"><section className="public-panel"><h1>领取页不可用</h1><p>批次不存在、未发布或已过期。</p></section></main>;
  }

  return (
    <main className="public-shell">
      <section className="public-panel">
        <h1>{batch?.name ?? "节点包领取"}</h1>
        <p>{batch?.description || "输入正确口令后即可下载加密节点包。领取页不会直接展示完整节点。"}</p>
        <div className="public-meta">
          <span>有效期：{batch?.expiresAt ? new Date(batch.expiresAt).toLocaleString() : "未设置"}</span>
        </div>

        <form className="login-form" onSubmit={verify}>
          <label>
            领取口令
            <input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} />
          </label>
          <button className="primary">验证口令</button>
        </form>

        {unlocked && (
          <a className="download-button" href={`/api/public/batches/${slug}/download${window.location.search}`}>
            <Download size={18} />
            下载加密节点包
          </a>
        )}

        {message && <div className="notice">{message}</div>}

        <form className="feedback-form" onSubmit={submitFeedback}>
          <h2>简单反馈</h2>
          <input placeholder="地区" value={feedback.region} onChange={(event) => setFeedback((value) => ({ ...value, region: event.target.value }))} />
          <input placeholder="运营商" value={feedback.carrier} onChange={(event) => setFeedback((value) => ({ ...value, carrier: event.target.value }))} />
          <input placeholder="设备" value={feedback.device} onChange={(event) => setFeedback((value) => ({ ...value, device: event.target.value }))} />
          <input placeholder="使用软件" value={feedback.clientApp} onChange={(event) => setFeedback((value) => ({ ...value, clientApp: event.target.value }))} />
          <label className="check-row">
            <input type="checkbox" checked={feedback.isUsable} onChange={(event) => setFeedback((value) => ({ ...value, isUsable: event.target.checked }))} />
            本批次可用
          </label>
          <textarea placeholder="备注" value={feedback.note} onChange={(event) => setFeedback((value) => ({ ...value, note: event.target.value }))} />
          <button className="primary small">提交反馈</button>
        </form>
      </section>
    </main>
  );
}

function RunTable({ runs }: { runs: CollectionRun[] }) {
  return (
    <div className="table">
      <div className="table-head run-grid"><span>任务</span><span>状态</span><span>来源</span><span>原始</span><span>新增</span><span>错误</span></div>
      {runs.slice(0, 12).map((run) => (
        <div className="table-row run-grid" key={run.id}>
          <span>#{run.id}</span><span>{run.status}</span><span>{run.fetched_sources}/{run.discovered_sources}</span><span>{run.raw_nodes}</span><span>{run.inserted_nodes}</span><span>{run.error_count}</span>
        </div>
      ))}
      {!runs.length && <p className="muted">暂无采集任务记录。</p>}
    </div>
  );
}

function TestRunTable({ runs }: { runs: TestRun[] }) {
  return (
    <div className="table">
      <div className="table-head run-grid"><span>任务</span><span>状态</span><span>测试</span><span>通过</span><span>失败</span><span>均值</span></div>
      {runs.slice(0, 12).map((run) => (
        <div className="table-row run-grid" key={run.id}>
          <span>#{run.id}</span><span>{run.status}</span><span>{run.tested_nodes}</span><span>{run.passed_nodes}</span><span>{run.failed_nodes}</span><span>{run.avg_latency_ms ? `${run.avg_latency_ms}ms` : "-"}</span>
        </div>
      ))}
      {!runs.length && <p className="muted">暂无测试任务记录。</p>}
    </div>
  );
}

function BatchTable({ batches, compact = false, claimOnly = false }: { batches: ExportBatch[]; compact?: boolean; claimOnly?: boolean }) {
  return (
    <div className="table spaced">
      <div className="table-head batch-grid"><span>批次</span><span>名称</span><span>状态</span><span>数量</span><span>领取页</span></div>
      {batches.slice(0, compact ? 6 : 50).map((batch) => {
        const claimUrl = `/p/${batch.public_slug}`;
        return (
          <div className="table-row batch-grid" key={batch.id}>
            <span>{batch.batch_code}</span>
            <span className="truncate">{batch.name}</span>
            <span>{batch.status}</span>
            <span>{batch.node_count}</span>
            <span className="row-actions">
              {batch.status === "published" || claimOnly ? (
                <a className="text-link" href={claimUrl} target="_blank" rel="noreferrer">打开领取页</a>
              ) : (
                <span className="muted">未发布</span>
              )}
            </span>
          </div>
        );
      })}
      {!batches.length && <p className="muted">暂无导出批次。</p>}
    </div>
  );
}

function NodePreview({ title, nodes }: { title: string; nodes: NodeItem[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>{title}</h2><Activity size={18} /></div>
      <NodeTable nodes={nodes} />
    </section>
  );
}

function NodeTable({ nodes }: { nodes: NodeItem[] }) {
  return (
    <div className="table">
      <div className="table-head node-grid"><span>协议</span><span>状态</span><span>后台初筛延迟</span><span>来源</span><span>最近测试</span><span>失败原因</span></div>
      {nodes.map((node) => (
        <div className="table-row node-grid" key={node.id}>
          <span>{node.protocol}</span>
          <span>{node.status}</span>
          <span>{node.latency_ms ? `${node.latency_ms}ms` : "-"}</span>
          <span>{node.source_type ?? "-"}</span>
          <span>{formatDate(node.last_tested_at)}</span>
          <span className="truncate">{node.failure_reason ?? "-"}</span>
        </div>
      ))}
      {!nodes.length && <p className="muted">暂无节点记录。</p>}
    </div>
  );
}

function SourceCache({ sources, videoMode }: { sources: SourceItem[]; videoMode: boolean }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>来源缓存</h2><GitBranch size={18} /></div>
      <div className="table">
        <div className="table-head source-grid"><span>类型</span><span>状态</span><span>成功</span><span>失败</span><span>来源 URL</span></div>
        {sources.slice(0, 20).map((source) => (
          <div className="table-row source-grid" key={source.id}>
            <span>{source.source_type}</span><span>{source.status}</span><span>{source.success_count}</span><span>{source.failure_count}</span><span className="truncate">{videoMode ? maskUrl(source.url) : source.url}</span>
          </div>
        ))}
        {!sources.length && <p className="muted">暂无来源缓存。</p>}
      </div>
    </section>
  );
}

function LatencyDistribution({ summary }: { summary: Summary | null }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>后台初筛延迟分布</h2><Database size={18} /></div>
      <div className="distribution">
        {(summary?.latencyDistribution ?? []).map((item) => (
          <div key={item.label} className="bar-row">
            <span>{item.label}</span>
            <div className="bar"><i style={{ width: `${Math.min(item.count * 5, 100)}%` }} /></div>
            <strong>{item.count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function maskUrl(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}/...`;
  } catch {
    return "已隐藏";
  }
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return "-";
  return time.toLocaleString();
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
