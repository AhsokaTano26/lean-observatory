import { Code2, CheckCircle2, XCircle, Layers } from "lucide-react";
import type { Run, Metrics } from "../types";
import { number } from "../format";
import { Panel } from "./UI";
import { Chart } from "./Chart";
export function Compile({ run, history }: { run: Run; history: Metrics[] }) {
  const c = run.compile;
  return (
    <Panel
      title="编译监控"
      icon={<Code2 size={17} />}
      aside={<span className="micro mono">SOURCE BUILD</span>}
      className="compile-panel"
    >
      <div className="compile-body">
        <div className="row spread">
          <span>
            源码文件 <strong className="mono">{c.percent.toFixed(1)}%</strong>
          </span>
          <span className="muted mono">
            {number(c.succeeded)} / {number(c.total)}{" "}
            {c.total == null ? "（待盘点）" : ""}
          </span>
        </div>
        <div
          className="progress"
          role="progressbar"
          aria-label="编译进度"
          aria-valuenow={c.percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <span style={{ width: `${c.percent}%` }} />
        </div>
        <div className="compile-counts">
          <span>
            <CheckCircle2 size={13} />
            成功 <b>{number(c.succeeded)}</b>
          </span>
          <span>
            <XCircle size={13} />
            失败 <b>{number(c.failed)}</b>
          </span>
          <span>
            <Layers size={13} />
            待处理 <b>{number(c.remaining)}</b>
          </span>
        </div>
        <div className="chart-label">
          <span>
            编译吞吐历史 <span className="muted">/ files·s⁻¹</span>
          </span>
          <b className="blue mono">{number(c.rate)} files/s</b>
        </div>
        <Chart
          label="编译吞吐历史曲线"
          unit="files/s"
          values={history
            .filter((x) => x.runId === run.id)
            .map((x) => ({ x: x.observedAt || x.sampledAt || 0, y: x.rate }))}
        />
        <div className="module-line">
          <span className={`dot ${run.status === "running" ? "live" : ""}`} />
          <code>{c.currentModule || "等待编译任务 · 原始源码尚未加载"}</code>
        </div>
      </div>
    </Panel>
  );
}
