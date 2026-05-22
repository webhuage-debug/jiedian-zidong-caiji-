import React from "react";
import ReactDOM from "react-dom/client";
import { Eye, EyeOff, Gauge, LogOut, Moon, ShieldCheck, Video } from "lucide-react";
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
  publishedBatches: number;
  latencyDistribution: Array<{ label: string; count: number }>;
};

function App() {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);

  React.useEffect(() => {
    fetch("/api/auth/status").then((res) => res.json()).then(setAuth).catch(() => setAuth({ authenticated: false }));
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
            <p>个人 VPS 节点初筛后台</p>
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
  const [videoMode, setVideoMode] = React.useState(false);

  React.useEffect(() => {
    fetch("/api/dashboard/summary").then((res) => res.json()).then(setSummary);
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    onLogout();
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
            <p>v0.1.0 基础版：登录、Session、SQLite 和部署骨架已就绪。</p>
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
          <Metric label="候选节点" value={summary?.candidateNodes ?? 0} />
          <Metric label="待测试" value={summary?.pendingNodes ?? 0} />
          <Metric label="失败/剔除" value={summary?.failedNodes ?? 0} />
          <Metric label="已发布批次" value={summary?.publishedBatches ?? 0} />
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>后台初筛延迟分布</h2>
            <span>{summary?.systemStatus ?? "loading"}</span>
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

        <section className="panel">
          <div className="panel-title">
            <h2>v0.1.0 阶段说明</h2>
            <Moon size={18} />
          </div>
          <p className="muted">
            本阶段只完成项目基础能力。节点采集、协议识别、连通性测试、导出节点包和公开领取页会在后续版本按计划继续实现。
          </p>
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

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
