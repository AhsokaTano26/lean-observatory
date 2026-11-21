import { GitBranch, Check, LoaderCircle, Circle } from "lucide-react";
import type { Run } from "../types";
import { time, duration } from "../format";
import { Panel, Badge } from "./UI";
export function Timeline({ run, full = false }: { run: Run; full?: boolean }) {
  return (
    <Panel
      title="验证时间线"
      icon={<GitBranch size={17} />}
      aside={<span className="micro mono">{run.checksPassed} / 6</span>}
    >
      <ol className={`timeline ${full ? "full" : ""}`}>
        {run.stages.map((s, i) => (
          <li key={s.id} className={`step step-${s.status}`}>
            <div className="step-icon">
              {s.status === "passed" ? (
                <Check size={12} />
              ) : s.status === "running" ? (
                <LoaderCircle size={12} />
              ) : (
                <Circle size={11} />
              )}
            </div>
            <div className="step-content">
              <div className="row spread">
                <span className="step-title">{s.label}</span>
                <Badge status={s.status} />
              </div>
              <div className="row spread step-meta">
                <time>
                  {time(s.startedAt)}{" "}
                  {s.finishedAt ? "→ " + time(s.finishedAt) : ""}
                </time>
                <span>
                  {s.exitCode != null
                    ? "exit " + s.exitCode
                    : i === 3
                      ? "Lean 4.33.1"
                      : ""}
                </span>
              </div>
              {full ? (
                <p className="muted">
                  {s.startedAt && s.finishedAt
                    ? `阶段耗时 ${duration(s.finishedAt - s.startedAt)}`
                    : s.status === "running"
                      ? "实际运行时间与日志由 Worker 上报"
                      : "等待上游阶段完成"}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
