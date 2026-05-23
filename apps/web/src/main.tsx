import React from "react";
import ReactDOM from "react-dom/client";
import { Activity, Database, Eye, EyeOff, Gauge, GitBranch, LogOut, Play, ShieldCheck, Video } from "lucide-react";
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
  source_type?: string;
  latency_ms?: number;
  status: string;
  failure_reason?: string;
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
};

type PublicBatch = {
  batchCode: string;
  name: string;
  description: string;
  nodeCount: number;
  expiresAt?: string | null;
  createdAt: string;
};

function App() {
  const publicMatch = window.location.pathname.match(/^\/p\/([^/]+)/);
  if (publicMatch) return <PublicClaimPage slug={publicMatch[1]} />;
  return <AdminApp />;
}

function AdminApp() {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);

  React.useEffect(() => {
    fetch("/api/auth/status")
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
    const res = await fetch("/api/auth/login", {
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
  const [summary, setSummary] = React.useState<Summary | null>(null);
  const [sources, setSources] = React.useState<SourceItem[]>([]);
  const [runs, setRuns] = React.useState<CollectionRun[]>([]);
  const [testRuns, setTestRuns] = React.useState<TestRun[]>([]);
  const [nodes, setNodes] = React.useState<NodeItem[]>([]);
  const [batches, setBatches] = React.useState<ExportBatch[]>([]);
  const [videoMode, setVideoMode] = React.useState(false);
  const [collecting, setCollecting] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [exporting, setExporting] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [exportForm, setExportForm] = React.useState({
    name: "本期候选节点",
    count: 10,
    maxLatencyMs: "",
    passphrase: "",
    publish: true
  });

  const refresh = React.useCallback(async () => {
    const [summaryRes, sourcesRes, runsRes, testRunsRes, nodesRes, batchesRes, videoModeRes] = await Promise.all([
      fetch("/api/dashboard/summary"),
      fetch("/api/sources"),
      fetch("/api/collection-runs"),
      fetch("/api/test-runs"),
      fetch("/api/nodes?limit=8"),
      fetch("/api/export-batches"),
      fetch("/api/settings/video-mode")
    ]);
    setSummary(await summaryRes.json());
    setSources((await sourcesRes.json()).items ?? []);
    setRuns((await runsRes.json()).items ?? []);
    setTestRuns((await testRunsRes.json()).items ?? []);
    setNodes((await nodesRes.json()).items ?? []);
    setBatches((await batchesRes.json()).items ?? []);
    setVideoMode(Boolean((await videoModeRes.json()).enabled));
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    onLogout();
  }

  async function runCollector() {
    setCollecting(true);
    setNotice("");
    const res = await fetch("/api/collection-runs", { method: "POST" });
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
    const res = await fetch("/api/test-runs", {
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
    const res = await fetch("/api/export-batches", {
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
      setNotice(data.message ?? "导出失败");
      return;
    }
    setNotice(`已生成批次 ${data.batch.batchCode}，导出节点 ${data.batch.nodeCount} 条。`);
    setExportForm((value) => ({ ...value, passphrase: "" }));
    await refresh();
  }

  async function toggleVideoMode() {
    const next = !videoMode;
    setVideoMode(next);
    await fetch("/api/settings/video-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: next })
    });
    await refresh();
  }

  const displayUser = videoMode ? "已隐藏" : user.username;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-title"><Gauge size={24} /> 管理后台</div>
        {["首页仪表盘", "节点池", "采集任务", "测试记录", "失效记录", "节点包", "领取页", "统计数据", "反馈数据", "系统设置", "运行日志"].map((item) => (
          <button key={item} className={item === "首页仪表盘" ? "nav active" : "nav"}>{item}</button>
        ))}
      </aside>
      <section className="content">
        <header className="topbar">
          <div>
            <h1>首页仪表盘</h1>
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

        <section className="metrics">
          <Metric label="已采集节点" value={summary?.collectedNodes ?? 0} />
          <Metric label="待测试节点" value={summary?.pendingNodes ?? 0} />
          <Metric label="候选节点" value={summary?.candidateNodes ?? 0} />
          <Metric label="失败/剔除" value={summary?.failedNodes ?? 0} />
        </section>

        {notice && <div className="notice">{notice}</div>}

        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>节点包导出</h2>
              <p className="muted compact">默认导出 10 条，可手动改成 11、20、30 或自定义数量。</p>
            </div>
          </div>
          <form className="export-form" onSubmit={createExport}>
            <label>
              批次名称
              <input value={exportForm.name} onChange={(event) => setExportForm((value) => ({ ...value, name: event.target.value }))} />
            </label>
            <label>
              导出数量
              <input type="number" min="1" max="1000" value={exportForm.count} onChange={(event) => setExportForm((value) => ({ ...value, count: Number(event.target.value) }))} />
            </label>
            <label>
              最大延迟 ms
              <input placeholder="例如 300" value={exportForm.maxLatencyMs} onChange={(event) => setExportForm((value) => ({ ...value, maxLatencyMs: event.target.value }))} />
            </label>
            <label>
              本期口令
              <input type="password" value={exportForm.passphrase} onChange={(event) => setExportForm((value) => ({ ...value, passphrase: event.target.value }))} required />
            </label>
            <label className="check-row">
              <input type="checkbox" checked={exportForm.publish} onChange={(event) => setExportForm((value) => ({ ...value, publish: event.target.checked }))} />
              发布领取页
            </label>
            <button className="primary small" disabled={exporting}>{exporting ? "生成中..." : "生成节点包"}</button>
          </form>
          <BatchTable batches={batches} />
        </section>

        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>采集任务</h2>
              <p className="muted compact">采集任务已限制频率和并发，只抓取公开 URL。</p>
            </div>
            <button className="primary small" onClick={runCollector} disabled={collecting}>
              <Play size={16} />
              {collecting ? "采集中..." : "开始采集"}
            </button>
          </div>
          <RunTable runs={runs} />
        </section>

        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>基础测试</h2>
              <p className="muted compact">只做后台初筛 TCP 连通性测试，失败节点不进入候选池。</p>
            </div>
            <button className="primary small" onClick={runTester} disabled={testing}>
              <Activity size={16} />
              {testing ? "测试中..." : "开始测试"}
            </button>
          </div>
          <TestRunTable runs={testRuns} />
        </section>

        <NodePreview nodes={nodes} />
        <SourceCache sources={sources} videoMode={videoMode} />
        <LatencyDistribution summary={summary} />
      </section>
    </main>
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
    fetch(`/api/public/batches/${slug}${window.location.search}`)
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
    const res = await fetch(`/api/public/batches/${slug}/verify${window.location.search}`, {
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
    setMessage("口令正确，可以下载节点包。");
  }

  async function submitFeedback(event: React.FormEvent) {
    event.preventDefault();
    const res = await fetch(`/api/public/batches/${slug}/feedback${window.location.search}`, {
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
        <p className="muted">批次编号：{batch?.batchCode ?? "-"}</p>
        <p>{batch?.description || "输入正确口令后即可下载加密节点包。领取页不会直接展示完整节点。"}</p>
        <div className="public-meta">
          <span>节点数量：{batch?.nodeCount ?? 0}</span>
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
      {runs.slice(0, 6).map((run) => (
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
      {runs.slice(0, 6).map((run) => (
        <div className="table-row run-grid" key={run.id}>
          <span>#{run.id}</span><span>{run.status}</span><span>{run.tested_nodes}</span><span>{run.passed_nodes}</span><span>{run.failed_nodes}</span><span>{run.avg_latency_ms ? `${run.avg_latency_ms}ms` : "-"}</span>
        </div>
      ))}
      {!runs.length && <p className="muted">暂无测试任务记录。</p>}
    </div>
  );
}

function BatchTable({ batches }: { batches: ExportBatch[] }) {
  return (
    <div className="table spaced">
      <div className="table-head batch-grid"><span>批次</span><span>名称</span><span>状态</span><span>数量</span><span>领取页</span></div>
      {batches.slice(0, 6).map((batch) => (
        <div className="table-row batch-grid" key={batch.id}>
          <span>{batch.batch_code}</span><span className="truncate">{batch.name}</span><span>{batch.status}</span><span>{batch.node_count}</span><span className="truncate">/p/{batch.public_slug}</span>
        </div>
      ))}
      {!batches.length && <p className="muted">暂无导出批次。</p>}
    </div>
  );
}

function NodePreview({ nodes }: { nodes: NodeItem[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>节点池预览</h2><Activity size={18} /></div>
      <div className="table">
        <div className="table-head node-grid"><span>协议</span><span>状态</span><span>后台初筛延迟</span><span>来源</span><span>失败原因</span></div>
        {nodes.map((node) => (
          <div className="table-row node-grid" key={node.id}>
            <span>{node.protocol}</span><span>{node.status}</span><span>{node.latency_ms ? `${node.latency_ms}ms` : "-"}</span><span>{node.source_type ?? "-"}</span><span className="truncate">{node.failure_reason ?? "-"}</span>
          </div>
        ))}
        {!nodes.length && <p className="muted">暂无节点记录。</p>}
      </div>
    </section>
  );
}

function SourceCache({ sources, videoMode }: { sources: SourceItem[]; videoMode: boolean }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>来源缓存</h2><GitBranch size={18} /></div>
      <div className="table">
        <div className="table-head source-grid"><span>类型</span><span>状态</span><span>成功</span><span>失败</span><span>来源 URL</span></div>
        {sources.slice(0, 8).map((source) => (
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

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
