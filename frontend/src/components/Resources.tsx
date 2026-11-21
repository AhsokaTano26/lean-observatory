import { Server, Cpu, MemoryStick, HardDrive, ArrowDownUp } from "lucide-react";
import type { Metrics } from "../types";
import { bytes, number } from "../format";
import { Panel } from "./UI";
import { Chart } from "./Chart";
function Meter({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: number | null | undefined;
  detail?: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="meter">
      <div className="row spread">
        <span>
          {icon}
          {label}
        </span>
        <span className="mono">
          {value == null ? "不可用" : number(value) + "%"}{" "}
          <small>{detail}</small>
        </span>
      </div>
      <div className="meter-track">
        <span style={{ width: `${value || 0}%` }} />
      </div>
    </div>
  );
}
export function Resources({
  metrics: m,
  history,
  full = false,
}: {
  metrics: Metrics;
  history: Metrics[];
  full?: boolean;
}) {
  return (
    <Panel
      title="服务器资源"
      icon={<Server size={17} />}
      aside={
        <span className="micro">
          {m.source === "mock_host"
            ? "MOCK HOST"
            : m.source === "host_agent"
              ? "HOST AGENT"
              : "LOCAL HOST"}
        </span>
      }
    >
      <div className="resources-body">
        {m.stale ? (
          <div className="inline-warning">宿主机指标已过期，等待采集器连接</div>
        ) : null}
        <Meter
          icon={<Cpu size={13} />}
          label="CPU"
          value={m.cpuPercent}
          detail={m.cpuCount ? `${m.cpuCount} 核` : ""}
        />
        <Meter
          icon={<MemoryStick size={13} />}
          label="内存"
          value={m.memoryPercent}
          detail={
            m.memoryTotalBytes
              ? `${bytes(m.memoryUsedBytes)} / ${bytes(m.memoryTotalBytes)}`
              : ""
          }
        />
        <Meter
          icon={<HardDrive size={13} />}
          label="磁盘"
          value={m.diskPercent}
          detail={`${bytes(m.diskUsedBytes)} / ${bytes(m.diskTotalBytes)}`}
        />
        <div className="chart-label">
          <span>CPU 使用率</span>
          <span className="mint micro">最近 {history.length} 次采样</span>
        </div>
        <Chart
          compact={!full}
          color="mint"
          label="CPU 使用率历史曲线"
          unit="%"
          stale={m.stale}
          max={100}
          values={history.map((x) => ({
            x: x.sampledAt || 0,
            y: x.cpuPercent,
          }))}
        />
        <div className="resource-footer">
          <span>
            <ArrowDownUp size={12} />
            <span className="mono">↓ {bytes(m.networkRxBytesPerSec)}/s</span>
            <span className="mono">↑ {bytes(m.networkTxBytesPerSec)}/s</span>
          </span>
          <span>
            负载{" "}
            <b className="mono">
              {m.load?.map((x) => number(x)).join(" · ") || "—"}
            </b>
          </span>
        </div>
        {m.limitations?.length ? (
          <p className="footnote">{m.limitations.join("；")}</p>
        ) : null}
      </div>
    </Panel>
  );
}
