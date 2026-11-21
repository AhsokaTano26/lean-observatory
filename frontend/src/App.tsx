import { useState, useEffect } from "react";
import {
  Home,
  Code2,
  Server,
  ScanSearch,
  GitBranch,
  ChartNoAxesColumn,
  Folder,
  Sun,
  Moon,
  Download,
  Pause,
  Play,
  Plus,
  Menu,
  X,
  ChevronRight,
  Clock3,
  Hourglass,
  Activity,
  Info,
  ArrowUpRight,
  KeyRound,
  Square,
} from "lucide-react";
import { useObservatory } from "./hooks/useObservatory";
import { Compile } from "./components/Compile";
import { Resources } from "./components/Resources";
import { Audits } from "./components/Audits";
import { Timeline } from "./components/Timeline";
import { Logs } from "./components/Logs";
import { Results } from "./components/Results";
import { Panel, Badge } from "./components/UI";
import { ServerCharts } from "./components/ServerCharts";
import { duration, number, bytes, time } from "./format";
const nav = [
  ["overview", "总览", Home],
  ["compile", "编译监控", Code2],
  ["server", "服务器监控", Server],
  ["audit", "证明审计", ScanSearch],
  ["timeline", "验证时间线", GitBranch],
  ["results", "结果中心", ChartNoAxesColumn],
] as const;
export default function App() {
  const [view, setView] = useState(() => location.hash.slice(1) || "overview"),
    [mobile, setMobile] = useState(false),
    [dialog, setDialog] = useState(false),
    [scenario, setScenario] = useState("success"),
    [mode, setMode] = useState("mock"),
    [jobs, setJobs] = useState(48),
    [tokenOpen, setTokenOpen] = useState(false),
    [token, setToken] = useState("");
  const [theme, setTheme] = useState(
    () => localStorage.getItem("lean-theme") || "light",
  );
  const {
    snapshot: p,
    logs,
    history,
    connection,
    error,
    busy,
    mutate,
    clearError,
  } = useObservatory();
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("lean-theme", theme);
  }, [theme]);
  useEffect(() => {
    const f = () => setView(location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  useEffect(() => {
    if (!dialog && !tokenOpen) return;
    const f = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDialog(false);
        setTokenOpen(false);
      }
    };
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, [dialog, tokenOpen]);
  const go = (v: string) => {
    location.hash = v;
    setView(v);
    setMobile(false);
  };
  const r = p?.run;
  const control = (action: string) =>
    r?.id && mutate("/api/control", { run: r.id, action });
  const create = async () => {
    const created = await mutate("/api/runs", { mode, scenario, jobs });
    if (created) {
      setDialog(false);
      go("overview");
    }
  };
  const active = !!r && ["running", "queued", "paused"].includes(r.status);
  return (
    <div className="app">
      <a
        href="#content"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault();
          const content = document.getElementById("content");
          content?.focus();
          content?.scrollIntoView({ block: "start" });
        }}
      >
        跳至主要内容
      </a>
      {mobile ? (
        <button
          className="sidebar-shade"
          aria-label="关闭导航"
          onClick={() => setMobile(false)}
        />
      ) : null}
      <header className="topbar" inert={dialog || tokenOpen}>
        <button
          className="icon-button mobile-menu"
          aria-label="打开导航"
          onClick={() => setMobile(true)}
        >
          <Menu size={19} />
        </button>
        <div className="breadcrumb">
          <Folder size={16} />
          <span>LEAN OBSERVATORY</span>
          <span className="slash">/</span>
          <span>独立验证观测台</span>
        </div>
        <div className="topbar-right">
          <span className={`connection connection-${connection}`}>
            <span className={`dot ${connection === "live" ? "live" : ""}`} />
            {connection === "live"
              ? "SSE 已连接"
              : connection === "connecting"
                ? "正在连接"
                : "断线重连中"}
          </span>
          <span className="top-divider" />
          <button
            className="icon-button"
            aria-label={theme === "dark" ? "切换浅色主题" : "切换深色主题"}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <button
            className="icon-button"
            aria-label="管理员令牌"
            onClick={() => setTokenOpen(true)}
          >
            <KeyRound size={16} />
          </button>
        </div>
      </header>
      <aside
        inert={dialog || tokenOpen}
        className={`sidebar ${mobile ? "is-open" : ""}`}
      >
        <a className="brand" href="#overview" onClick={() => go("overview")}>
          <span className="brand-mark">λ</span>
          <span>
            <b>
              LEAN<span className="brand-punctuation">.</span>OBSERVATORY
            </b>
            <small>RIEMANN HYPOTHESIS / INDEPENDENT VERIFICATION</small>
          </span>
        </a>
        <div className="nav-label">OBSERVATORY INDEX</div>
        <nav aria-label="主导航">
          {nav.map(([id, label, Icon], index) => (
            <a
              className={view === id ? "selected" : ""}
              href={"#" + id}
              key={id}
              onClick={() => go(id)}
              aria-current={view === id ? "page" : undefined}
            >
              <span className="nav-number" aria-hidden="true">
                0{index + 1}
              </span>
              <Icon size={18} />
              <span>{label}</span>
              {view === id ? <ChevronRight size={13} /> : null}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment">
            <span className="dot live" />
            <div>
              <span>验证环境</span>
              <b className="mono">Lean 4.33.1</b>
              <small>Mathlib · 0df444a3</small>
            </div>
          </div>
          <a
            className="repo-link"
            href="https://github.com/AhsokaTano26/lean-observatory"
            target="_blank"
            rel="noreferrer"
          >
            平台源码 <ArrowUpRight size={14} />
          </a>
          <div className="sidebar-caption">Evidence before conclusions.</div>
        </div>
      </aside>
      <div className="workspace" inert={dialog || tokenOpen}>
        <main id="content" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <div className="page-kicker">
                {String(nav.findIndex((n) => n[0] === view) + 1).padStart(
                  2,
                  "0",
                )}{" "}
                / {view.toUpperCase()}
              </div>
              <h1>
                {view === "overview"
                  ? "黎曼猜想 · 独立验证"
                  : nav.find((n) => n[0] === view)?.[1] ||
                    "黎曼猜想 · 独立验证"}
              </h1>
              <p>
                {view === "overview"
                  ? "从原始源码到内核重放，每一步均可追溯。"
                  : {
                      compile: "逐个模块跟踪源码编译与持久化日志。",
                      server: "系统负载与资源曲线，由实际采集器上报。",
                      audit: "五个最终定理的精确类型、依赖公理与内核重放。",
                      timeline: "阶段状态由实际命令、退出码与检查结果驱动。",
                      results: "下载验证记录、原始日志与可复现证据。",
                    }[view]}
              </p>
            </div>
            <div className="page-actions">
              <a
                className={`button secondary ${!r?.id ? "disabled" : ""}`}
                aria-disabled={!r?.id}
                href={r?.id ? `/api/report.json?run=${r.id}` : undefined}
              >
                <Download size={15} />
                下载报告
              </a>
              {active ? (
                <>
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() =>
                      control(r!.status === "paused" ? "resume" : "pause")
                    }
                  >
                    {r?.status === "paused" ? (
                      <Play size={14} />
                    ) : (
                      <Pause size={14} />
                    )}{" "}
                    {r?.status === "paused" ? "恢复任务" : "暂停任务"}
                  </button>
                  <button
                    className="icon-button stop"
                    title="取消任务"
                    aria-label="取消任务"
                    disabled={busy}
                    onClick={() => control("cancel")}
                  >
                    <Square size={14} />
                  </button>
                </>
              ) : r?.id &&
                ["failed", "interrupted", "resource_exhausted"].includes(
                  r.status,
                ) ? (
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => control("resume")}
                >
                  <Play size={14} />
                  恢复任务
                </button>
              ) : (
                <button
                  className="button primary"
                  onClick={() => setDialog(true)}
                  disabled={busy}
                >
                  <Plus size={15} />
                  新建任务
                </button>
              )}
            </div>
          </div>
          {r ? (
            <>
              <div
                className={`notice ${r.mode === "mock" ? "notice-mock" : "notice-real"}`}
              >
                <Info size={15} />
                <span>
                  {r.mode === "mock" ? (
                    <>
                      <b>MOCK</b>
                      <span className="notice-divider">·</span>
                      本地模拟数据，不代表真实证明结果
                    </>
                  ) : (
                    <>
                      <b>真实验证</b>
                      <span className="notice-divider">·</span>
                      {r.id
                        ? "所有检查以实际日志为准，未完成项保持待验证"
                        : "等待部署验收与真实任务启动"}
                    </>
                  )}
                </span>
                <span className="notice-right">
                  {r.id ? "RUN " + r.id : "NO ACTIVE RUN"}
                </span>
              </div>
              {error ? (
                <div className="error-alert" role="alert">
                  <Info size={16} />
                  <span>{error}</span>
                  <button
                    className="icon-button"
                    aria-label="关闭错误"
                    onClick={clearError}
                  >
                    <X size={14} />
                  </button>
                </div>
              ) : null}
              {r.error ? (
                <div className="error-alert" role="alert">
                  <Info size={16} />
                  <span>{r.error}</span>
                </div>
              ) : null}
              {r.id && active && !p?.workerOnline ? (
                <div className="inline-warning worker-warning">
                  Worker 尚未连接或心跳已过期；页面不会推算或推进真实任务。
                </div>
              ) : null}
              <div className="run-strip">
                <div>
                  <Badge status={r.status} />
                  <span className="muted">当前阶段</span>
                  <strong>
                    {r.stages.find((s) => s.id === r.phase)?.label}
                  </strong>
                </div>
                <span className="mono muted">
                  检查 {r.checksPassed}/6{" "}
                  <span className="mini-track">
                    <span style={{ width: `${r.overallPercent}%` }} />
                  </span>
                  {number(r.overallPercent)}%
                </span>
              </div>
              {view === "overview" || view === "compile" ? (
                <>
                  <div className="stats">
                    <div className="stat">
                      <span>
                        <Code2 size={16} />
                        编译进度
                      </span>
                      <div>
                        <b className="mint">
                          {r.compile.percent.toFixed(1)}
                          <small>%</small>
                        </b>
                        <span className="stat-sub mono">
                          {number(r.compile.succeeded)} /{" "}
                          {number(r.compile.total ?? r.compile.expectedTotal)}
                          {r.compile.total == null ? " 预期" : ""}
                        </span>
                      </div>
                    </div>
                    <div className="stat">
                      <span>
                        <Activity size={16} />
                        当前吞吐
                      </span>
                      <div>
                        <b className="blue">{number(r.compile.rate)}</b>
                        <span className="stat-sub">files/s</span>
                      </div>
                    </div>
                    <div className="stat">
                      <span>
                        <Clock3 size={16} />
                        已运行
                      </span>
                      <div>
                        <b className="mono">{duration(r.elapsedSeconds)}</b>
                      </div>
                    </div>
                    <div className="stat">
                      <span>
                        <Hourglass size={16} />
                        预计剩余
                      </span>
                      <div>
                        <b className="mono">{duration(r.compile.etaSeconds)}</b>
                        <span className="stat-sub">
                          {r.compile.etaSeconds == null
                            ? "等待有效采样"
                            : "基于近期吞吐"}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="overview-top">
                    <Compile run={r} history={history} />
                    <Resources metrics={p!.metrics} history={history} />
                  </div>
                  {view === "overview" ? (
                    <div className="overview-bottom">
                      <Audits run={r} />
                      <Timeline run={r} />
                    </div>
                  ) : (
                    <Panel title="编译统计口径">
                      <div className="text-block">
                        仅统计原始源码中的 Lean 模块，排除 Mathlib 依赖和 C
                        编译步骤；成功模块去重，完成后与实际 .olean
                        产物交叉核对。预计总量 {number(r.compile.expectedTotal)}
                        ，实测总量 {number(r.compile.total)}。吞吐量为最近 60
                        秒的模块完成速度；未获得有效样本时不估算 ETA。
                      </div>
                    </Panel>
                  )}
                  <Logs logs={logs} run={r} full={view === "compile"} />
                </>
              ) : null}
              {view === "server" ? (
                <ServerCharts metrics={p!.metrics} history={history} />
              ) : null}
              {view === "audit" ? <Audits run={r} full /> : null}
              {view === "timeline" ? (
                <>
                  <Timeline run={r} full />
                  <Logs run={r} logs={logs} />
                </>
              ) : null}
              {view === "results" ? <Results run={r} /> : null}
              <footer>
                <span>
                  <span className="dot" />{" "}
                  {r.mode === "mock" ? "本地模拟环境" : "独立复现环境"} · Lean
                  4.33.1
                </span>
                <span>
                  数学陈述复核：待完成 <span className="footer-divider">/</span>{" "}
                  独立内核：未执行
                </span>
              </footer>
            </>
          ) : (
            <div className="loading">
              <Activity size={24} />
              <h2>正在连接观测台</h2>
              <p>{error || "等待 API 返回任务状态…"}</p>
            </div>
          )}
        </main>
      </div>
      {dialog || tokenOpen ? (
        <div
          className="modal-backdrop"
          onClick={() => {
            setDialog(false);
            setTokenOpen(false);
          }}
        >
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="row spread">
              <h2 id="dialog-title">
                {tokenOpen ? "管理员访问" : "新建验证任务"}
              </h2>
              <button
                className="icon-button"
                aria-label="关闭对话框"
                onClick={() => {
                  setDialog(false);
                  setTokenOpen(false);
                }}
              >
                <X size={18} />
              </button>
            </div>
            {tokenOpen ? (
              <>
                <p className="muted">
                  令牌仅在当前标签页会话中保存，用于任务控制接口。
                </p>
                <label className="field">
                  管理员令牌
                  <input
                    autoFocus
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <button
                  className="button primary"
                  onClick={() => {
                    sessionStorage.setItem("lean-admin-token", token);
                    setToken("");
                    setTokenOpen(false);
                  }}
                >
                  保存令牌
                </button>
              </>
            ) : (
              <>
                <p className="muted">
                  模拟场景只生成测试数据。真实任务需通过部署验收门禁。
                </p>
                <label className="field">
                  任务模式
                  <select
                    autoFocus
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="mock">MOCK · 本地流程模拟</option>
                    <option
                      value="real"
                      disabled={!p?.capabilities.realEnabled}
                    >
                      真实源码验证
                      {!p?.capabilities.realEnabled ? "（部署门禁未通过）" : ""}
                    </option>
                  </select>
                </label>
                {mode === "mock" ? (
                  <label className="field">
                    模拟场景
                    <select
                      value={scenario}
                      onChange={(e) => setScenario(e.target.value)}
                    >
                      <option value="success">成功 · 完整阶段</option>
                      <option value="failure">失败 · 编译错误</option>
                      <option value="interruption">中断 · Worker 停止</option>
                      <option value="resource">资源不足 · 内存告警</option>
                    </select>
                  </label>
                ) : (
                  <label className="field">
                    Lake 调度线程
                    <input
                      type="number"
                      min={1}
                      max={52}
                      value={jobs}
                      onChange={(e) => setJobs(Number(e.target.value))}
                    />
                  </label>
                )}
                {error ? (
                  <div role="alert" className="error-alert">
                    {error}
                  </div>
                ) : null}
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={create}
                >
                  <Play size={14} />
                  {busy ? "创建中…" : "创建并开始"}
                </button>
              </>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}
