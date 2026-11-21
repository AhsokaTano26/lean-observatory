import { Download, FileCheck2, FileText, Copy, Check } from "lucide-react";
import { useState } from "react";
import type { Run } from "../types";
import { bytes, number } from "../format";
import { Panel, Badge, Empty } from "./UI";
export function Results({ run: r }: { run: Run }) {
  const [copied, setCopied] = useState(false);
  return (
    <>
      <div className="result-downloads">
        {[
          ["JSON 结构化报告", "report.json"],
          ["Markdown 验证报告", "report.md"],
          ["完整原始日志", "logs/download"],
        ].map(([name, path]) => (
          <a
            className="download-card"
            href={`/api/${path}?run=${r.id}`}
            key={path}
          >
            <FileText size={22} />
            <span>
              {name}
              <small>
                {r.mode === "mock" ? "含 MOCK 标识" : "包含真实阶段证据"}
              </small>
            </span>
            <Download size={17} />
          </a>
        ))}
      </div>
      <div className="result-grid">
        <Panel title="源码与完整性" icon={<FileCheck2 size={17} />}>
          <dl className="details">
            <dt>原始站点</dt>
            <dd>
              <a
                href="https://alpo.ge/remark.pdf"
                target="_blank"
                rel="noreferrer"
              >
                alpo.ge / remark.pdf ↗
              </a>
            </dd>
            <dt>归档校验</dt>
            <dd>
              <Badge status={r.provenance.integrity} />
            </dd>
            <dt>预期大小</dt>
            <dd className="mono">{number(r.provenance.expectedBytes)} bytes</dd>
            <dt>实测大小</dt>
            <dd className="mono">
              {r.provenance.bytes == null
                ? "待下载"
                : number(r.provenance.bytes) + " bytes"}
            </dd>
            <dt>预期 SHA-256</dt>
            <dd className="hash">{r.provenance.expectedSha256}</dd>
            <dt>实测 SHA-256</dt>
            <dd className="hash">
              {r.provenance.sha256 || "待校验"}
              {r.provenance.sha256 ? (
                <button
                  className="icon-button"
                  aria-label="复制 SHA-256"
                  onClick={async () => {
                    await navigator.clipboard.writeText(r.provenance.sha256!);
                    setCopied(true);
                  }}
                >
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                </button>
              ) : null}
            </dd>
            <dt>哈希来源</dt>
            <dd>{r.provenance.hashSource}</dd>
            <dt>源码清单哈希</dt>
            <dd className="hash">{r.provenance.inventorySha256 || "待生成"}</dd>
          </dl>
        </Panel>
        <Panel title="可复现环境">
          <dl className="details">
            <dt>Lean（锁定）</dt>
            <dd className="mono">{r.environment.lean}</dd>
            <dt>Lean（实测）</dt>
            <dd>{r.environment.actualLean || "待采集"}</dd>
            <dt>Mathlib（锁定）</dt>
            <dd className="hash">{r.environment.mathlib}</dd>
            <dt>Mathlib（实测）</dt>
            <dd className="hash">{r.environment.actualMathlib || "待采集"}</dd>
            <dt>系统 / Python</dt>
            <dd>
              {r.environment.platform || "待采集"} /{" "}
              {r.environment.python || "—"}
            </dd>
            <dt>并发配置</dt>
            <dd>{r.compile.jobs} 个 Lake 调度线程 · Lean 子进程 -j1</dd>
            <dt>任务标识</dt>
            <dd className="mono">{r.id || "暂无任务"}</dd>
          </dl>
        </Panel>
      </div>
      <Panel
        title="证据文件"
        aside={<span className="micro">SHA-256 ADDRESSED</span>}
      >
        {r.artifacts.length ? (
          <div className="artifact-list">
            {r.artifacts.map((a) => (
              <a href={`/api/artifacts/${a.name}?run=${r.id}`} key={a.name}>
                <FileText size={17} />
                <div>
                  <b>{a.name}</b>
                  <code>{a.sha256}</code>
                </div>
                <span className="muted">{bytes(a.bytes)}</span>
                <Download size={15} />
              </a>
            ))}
          </div>
        ) : (
          <Empty>
            当前任务尚未产生真实证据文件。Mock 报告可通过上方入口下载。
          </Empty>
        )}
      </Panel>
      <Panel title="命令与退出码">
        {r.commands.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>阶段</th>
                  <th>命令参数</th>
                  <th>退出码</th>
                </tr>
              </thead>
              <tbody>
                {r.commands.map((c, i) => (
                  <tr key={i}>
                    <td>{c.stage}</td>
                    <td>
                      <code>{c.argv.join(" ")}</code>
                    </td>
                    <td>
                      <Badge
                        status={
                          c.exitCode == null
                            ? "running"
                            : c.exitCode === 0
                              ? "passed"
                              : "failed"
                        }
                      />
                      <span className="mono"> {c.exitCode}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>真实命令尚未执行</Empty>
        )}
      </Panel>
    </>
  );
}
