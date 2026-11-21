import { useState } from "react";
import {
  Cpu,
  MemoryStick,
  HardDrive,
  ArrowDownUp,
  Activity,
  Server,
} from "lucide-react";
import type { Metrics } from "../types";
import { bytes, number, time } from "../format";
import { Chart } from "./Chart";
import { Panel } from "./UI";

const windows = [
  { seconds: 60, label: "1 分钟" },
  { seconds: 300, label: "5 分钟" },
  { seconds: 900, label: "15 分钟" },
  { seconds: 1800, label: "30 分钟" },
];
export function ServerCharts({
  metrics: m,
  history,
}: {
  metrics: Metrics;
  history: Metrics[];
}) {
  const [windowSeconds, setWindow] = useState(() => {
    const n = Number(new URLSearchParams(location.search).get("window"));
    return windows.some((w) => w.seconds === n) ? n : 300;
  });
  const select = (n: number) => {
    setWindow(n);
    const url = new URL(location.href);
    url.searchParams.set("window", String(n));
    window.history.replaceState(null, "", url);
  };
  const points = (field: "cpuPercent" | "memoryPercent" | "diskPercent") =>
    history.map((s) => ({ x: s.sampledAt || 0, y: s[field] }));
  const pct = (n: number | null | undefined) =>
    n == null ? "—" : number(n) + "%";
  return (
    <>
      <div className="metrics-toolbar">
        <div>
          <span className={`dot ${m.stale ? "" : "live"}`} />
          <span>
            {m.source === "mock_host" ? "模拟服务器" : "宿主机"}性能趋势
          </span>
          <small>更新于 {time(m.sampledAt)}</small>
        </div>
        <div className="chart-ranges" role="group" aria-label="图表时间范围">
          {windows.map((w) => (
            <button
              key={w.seconds}
              aria-pressed={windowSeconds === w.seconds}
              onClick={() => select(w.seconds)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>
      {m.stale ? (
        <div className="inline-warning">采集器未更新，保留最近有效数据</div>
      ) : null}
      <div className="server-charts-grid">
        <Panel
          title="CPU 使用率"
          icon={<Cpu size={16} />}
          aside={
            <span className="metric-current mint">
              {pct(m.cpuPercent)}
              <small>{m.cpuCount || "—"} vCPU</small>
            </span>
          }
          className="metric-chart-card"
        >
          <Chart
            label="CPU 使用率历史曲线"
            unit="%"
            color="mint"
            max={100}
            values={points("cpuPercent")}
            windowSeconds={windowSeconds}
            stale={m.stale}
          />
        </Panel>
        <Panel
          title="内存使用率"
          icon={<MemoryStick size={16} />}
          aside={
            <span className="metric-current blue">
              {pct(m.memoryPercent)}
              <small>
                {bytes(m.memoryUsedBytes)} / {bytes(m.memoryTotalBytes)}
              </small>
            </span>
          }
          className="metric-chart-card"
        >
          <Chart
            label="内存使用率历史曲线"
            unit="%"
            max={100}
            values={points("memoryPercent")}
            windowSeconds={windowSeconds}
            stale={m.stale}
          />
        </Panel>
        <Panel
          title="网络吞吐"
          icon={<ArrowDownUp size={16} />}
          aside={<span className="micro">非回环接口合计</span>}
          className="metric-chart-card metric-chart-network"
        >
          <Chart
            label="网络吞吐历史曲线"
            unit="MiB/s"
            windowSeconds={windowSeconds}
            stale={m.stale}
            series={[
              {
                id: "rx",
                name: "下载",
                color: "mint",
                values: history.map((s) => ({
                  x: s.sampledAt || 0,
                  y:
                    s.networkRxBytesPerSec == null
                      ? null
                      : s.networkRxBytesPerSec / 1024 ** 2,
                })),
              },
              {
                id: "tx",
                name: "上传",
                color: "blue",
                dashed: true,
                values: history.map((s) => ({
                  x: s.sampledAt || 0,
                  y:
                    s.networkTxBytesPerSec == null
                      ? null
                      : s.networkTxBytesPerSec / 1024 ** 2,
                })),
              },
            ]}
          />
        </Panel>
        <Panel
          title="磁盘占用"
          icon={<HardDrive size={16} />}
          aside={
            <span className="metric-current">
              {pct(m.diskPercent)}
              <small>
                {bytes(m.diskUsedBytes)} / {bytes(m.diskTotalBytes)}
              </small>
            </span>
          }
          className="metric-chart-card"
        >
          <Chart
            label="磁盘使用量历史曲线"
            unit="GiB"
            color="violet"
            values={history.map((s) => ({
              x: s.sampledAt || 0,
              y: s.diskUsedBytes == null ? null : s.diskUsedBytes / 1024 ** 3,
            }))}
            windowSeconds={windowSeconds}
            stale={m.stale}
          />
        </Panel>
        <Panel
          title="系统负载"
          icon={<Activity size={16} />}
          aside={
            <span className="metric-current">
              {number(m.load?.[0])}
              <small>1 分钟负载</small>
            </span>
          }
          className="metric-chart-card"
        >
          <Chart
            label="系统负载历史曲线"
            unit="load"
            color="blue"
            values={history.map((s) => ({
              x: s.sampledAt || 0,
              y: s.load?.[0],
            }))}
            windowSeconds={windowSeconds}
            stale={m.stale}
          />
        </Panel>
      </div>
      <Panel title="采集环境" icon={<Server size={16} />}>
        <dl className="details">
          <dt>采集源</dt>
          <dd>{m.source}</dd>
          <dt>主机名</dt>
          <dd className="mono">{m.hostname || "等待宿主机采集器"}</dd>
          <dt>系统</dt>
          <dd>{m.platform || "—"}</dd>
          <dt>采样时间</dt>
          <dd>{time(m.sampledAt)}</dd>
        </dl>
      </Panel>
    </>
  );
}
