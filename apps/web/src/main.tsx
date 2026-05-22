import React from "react";
import ReactDOM from "react-dom/client";
import { Database, Eye, EyeOff, Gauge, GitBranch, LogOut, Play, ShieldCheck, Video } from "lucide-react";
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
  recentCollection?: CollectionRun | null;
  latencyDistribution: Array<{ label: string; count: number }>;
};

type CollectionRun = {
  id: number;
  status: string;
  started_at: string;
  finished_at?: string;
  discovered_sources: number;
  fetched_sources: number;
  raw_nodes: number;
  deduped_nodes: number;
  inserted_nodes: number;
  error_count: number;
};

type SourceItem = {
  id: number;
  url: string;
  source_type: string;
  status: string;
  success_count: number;
  failure_count: number;
  last_checked_at?: string;
  next_allowed_at?: string;
  last_error?: string;
};

function App() {
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
  const [videoMode, setVideoMode] = React.useState(false);
  const [collecting, setCollecting] = React.useState(false);
  const [notice, setNotice] = React.useState("");

  const refresh = React.useCallback(async () => {
    const [summaryRes, sourcesRes, runsRes] = await Promise.all([
      fetch("/api/dashboard/summary"),
      fetch("/api/sources"),
      fetch("/api/collection-runs")
    ]);
    setSummary(await summaryRes.json());
    setSources((await sourcesRes.json()).items ?? []);
    setRuns((await runsRes.json()).items ?? []);
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
            <p>v0.2.0 采集版：公开来源发现、节点提取、去重和入库。</p>
          </div>
          <div className="top-actions">
            <button className={videoMode ? "icon active" : "icon"} onClick={() => setVideoMode((value) => !value)} title="公开视频模式">
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
          {notice && <div className="notice">{notice}</div>}
          <div className="table">
            <div className="table-head run-grid">
              <span>任务</span><span>状态</span><span>来源</span><span>原始</span><span>新增</span><span>错误</span>
            </div>
            {runs.slice(0, 6).map((run) => (
              <div className="table-row run-grid" key={run.id}>
                <span>#{run.id}</span>
                <span>{run.status}</span>
                <span>{run.fetched_sources}/{run.discovered_sources}</span>
                <span>{run.raw_nodes}</span>
                <span>{run.inserted_nodes}</span>
                <span>{run.error_count}</span>
              </div>
            ))}
            {!runs.length && <p className="muted">暂无采集任务记录。</p>}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>来源缓存</h2>
            <GitBranch size={18} />
          </div>
          <div className="table">
            <div className="table-head source-grid">
              <span>类型</span><span>状态</span><span>成功</span><span>失败</span><span>来源 URL</span>
            </div>
            {sources.slice(0, 8).map((source) => (
              <div className="table-row source-grid" key={source.id}>
                <span>{source.source_type}</span>
                <span>{source.status}</span>
                <span>{source.success_count}</span>
                <span>{source.failure_count}</span>
                <span className="truncate">{videoMode ? maskUrl(source.url) : source.url}</span>
              </div>
            ))}
            {!sources.length && <p className="muted">暂无来源缓存。</p>}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>后台初筛延迟分布</h2>
            <Database size={18} />
          </div>
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
      </section>
    </main>
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
