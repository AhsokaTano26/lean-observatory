import { ScanSearch, ChevronDown } from "lucide-react";
import { useState } from "react";
import type { Run } from "../types";
import { Panel, Badge } from "./UI";
export function Audits({ run, full = false }: { run: Run; full?: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <Panel
      title="证明审计"
      icon={<ScanSearch size={17} />}
      aside={<span className="micro">5 FINAL THEOREMS</span>}
    >
      <div className="table-wrap audit-table-wrap">
        <table>
          <thead>
            <tr>
              <th>定理 / Theorem</th>
              <th>类型</th>
              <th>公理</th>
              <th>内核重放</th>
            </tr>
          </thead>
          <tbody>
            {run.audits.map((a) => (
              <tr key={a.name}>
                <td>
                  <button
                    className="theorem-button"
                    onClick={() =>
                      setExpanded(expanded === a.name ? null : a.name)
                    }
                    aria-expanded={expanded === a.name}
                  >
                    <code>{a.name}</code>
                    <ChevronDown size={12} />
                  </button>
                  {expanded === a.name ? (
                    <div className="audit-detail">
                      <p>
                        期望类型：<code>{a.expectedType}</code>
                      </p>
                      <p>
                        依赖公理：
                        {a.axioms === "pending"
                          ? "待实测"
                          : a.dependencies.join(", ") || "无"}
                      </p>
                      <p>{a.output || "审计输出尚未生成"}</p>
                    </div>
                  ) : null}
                  <div className="mobile-audit-summary">
                    <span>
                      类型 <Badge status={a.type} />
                    </span>
                    <span>
                      公理 <Badge status={a.axioms} />
                    </span>
                    <span>
                      重放 <Badge status={a.replay} />
                    </span>
                  </div>
                </td>
                <td>
                  <Badge status={a.type} />
                </td>
                <td>
                  <Badge status={a.axioms} />
                </td>
                <td>
                  <Badge status={a.replay} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {full ? (
        <div className="audit-notes">
          <h3>验证边界</h3>
          <p>
            精确类型检查 + 传递公理白名单：
            <code>propext / Classical.choice / Quot.sound</code>
            。发现额外公理、潜在绕过点或缺少输出时阻止后续通过。
          </p>
          <div className="row">
            <span>数学陈述语义复核</span>
            <Badge status="pending" />
          </div>
          <div className="row">
            <span>不同实现的独立内核</span>
            <Badge status="not_run" />
          </div>
          <p className="muted">
            leanchecker 以独立进程重放同一 Lean
            内核，不等同于另一实现的内核验证。类型名相同也不能替代数学定义的人工复核。
          </p>
        </div>
      ) : null}
    </Panel>
  );
}
