import { useEffect, useMemo, useRef, useState } from "react";
import { Terminal, Search, Download, Pause, Play } from "lucide-react";
import type { Log, Run } from "../types";
import { time } from "../format";
import { Panel, Empty } from "./UI";
export function Logs({
  logs,
  run,
  full = false,
}: {
  logs: Log[];
  run: Run;
  full?: boolean;
}) {
  const [query, setQuery] = useState(""),
    [level, setLevel] = useState("all"),
    [follow, setFollow] = useState(true);
  const end = useRef<HTMLDivElement>(null);
  const filtered = useMemo(
    () =>
      logs.filter(
        (l) =>
          (level === "all" || l.level === level) &&
          l.message.toLowerCase().includes(query.toLowerCase()),
      ),
    [logs, query, level],
  );
  useEffect(() => {
    if (follow && end.current?.parentElement) {
      const terminal = end.current.parentElement;
      terminal.scrollTop = terminal.scrollHeight;
    }
  }, [logs, follow]);
  return (
    <Panel
      title="实时日志"
      icon={<Terminal size={17} />}
      aside={
        <div className="row">
          <span className="micro">
            {run.mode === "mock" ? "MOCK STREAM" : "WORKER STREAM"}
          </span>
          <button
            className="icon-button"
            aria-label={follow ? "暂停日志滚动" : "恢复日志滚动"}
            onClick={() => setFollow(!follow)}
          >
            {follow ? <Pause size={14} /> : <Play size={14} />}
          </button>
          <a
            className="icon-button"
            aria-label="下载完整日志"
            href={`/api/logs/download?run=${run.id}`}
          >
            <Download size={14} />
          </a>
        </div>
      }
      className="logs-panel"
    >
      <div className="log-toolbar">
        <label className="search">
          <Search size={14} />
          <input
            aria-label="筛选实时日志"
            placeholder="筛选当前日志…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="日志级别"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
        >
          <option value="all">全部级别</option>
          <option value="error">错误</option>
          <option value="warning">警告</option>
          <option value="info">信息</option>
        </select>
        <span className="micro">{filtered.length} 行 · 窗口 500</span>
      </div>
      <div
        className={`terminal ${full ? "terminal-full" : ""}`}
        role="log"
        aria-label="实时验证日志"
      >
        <div>
          {filtered.length ? (
            filtered.map((l) => (
              <div className={`log-line log-${l.level}`} key={l.id}>
                <span className="log-time">{time(l.ts)}</span>
                <span className="log-stage">[{l.stage}]</span>
                <span>{l.message}</span>
              </div>
            ))
          ) : (
            <Empty>{query ? "当前窗口没有匹配日志" : "等待任务日志"}</Empty>
          )}
        </div>
        <div ref={end} />
      </div>
    </Panel>
  );
}
