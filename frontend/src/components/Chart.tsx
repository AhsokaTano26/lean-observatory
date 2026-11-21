import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { area, line, curveMonotoneX } from "d3-shape";
import { Activity } from "lucide-react";
import {
  chartDomain,
  chartTicks,
  formatTick,
  nearestPoint,
  normalizePoints,
  positionX,
  sampleGap,
  splitPoints,
} from "../chartMath";
import type { ChartPoint, DefinedPoint } from "../chartMath";
import { number, time } from "../format";

export interface ChartSeries {
  id: string;
  name: string;
  color: "blue" | "mint" | "amber" | "violet";
  values: ChartPoint[];
  dashed?: boolean;
}
type Props = {
  values?: ChartPoint[];
  series?: ChartSeries[];
  color?: ChartSeries["color"];
  label: string;
  unit?: string;
  max?: number;
  compact?: boolean;
  windowSeconds?: number;
  stale?: boolean;
  showSummary?: boolean;
};

export function Chart({
  values = [],
  series,
  color = "blue",
  label,
  unit = "",
  max,
  compact = false,
  windowSeconds = 300,
  stale = false,
  showSummary = !compact,
}: Props) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const root = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 600, height: 200 });
  const [selected, setSelected] = useState<number | null>(null);
  useLayoutEffect(() => {
    const node = root.current;
    if (!node) return;
    const measure = () => {
      const box = node.getBoundingClientRect();
      setSize((old) => {
        const next = {
          width: Math.round(box.width),
          height: Math.round(box.height),
        };
        return old.width === next.width && old.height === next.height
          ? old
          : next;
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const sources = useMemo(
    () =>
      (series || [{ id: "primary", name: label, color, values }]).map((s) => ({
        ...s,
        values: normalizePoints(s.values),
      })),
    [series, values, color, label],
  );
  const allTimes = sources.flatMap((s) => s.values.map((p) => p.x));
  const end = allTimes.length ? Math.max(...allTimes) : 0;
  const first = allTimes.length ? Math.min(...allTimes) : 0;
  const beginning = Math.max(first, end - windowSeconds);
  const xDomain: [number, number] = [
    beginning === end ? end - 60 : beginning,
    end || 60,
  ];
  const visible = sources.map((s) => ({
    ...s,
    values: s.values.filter((p) => p.x >= beginning && p.x <= end),
  }));
  const primary = visible[0];
  const valid =
    primary?.values.filter(
      (p): p is DefinedPoint => p.y != null && Number.isFinite(p.y),
    ) || [];
  const allValues = visible.flatMap((s) =>
    s.values.flatMap((p) => (p.y != null ? [p.y] : [])),
  );
  const domain = chartDomain(allValues, max);
  const width = Math.max(220, size.width),
    height = Math.max(compact ? 118 : 150, size.height);
  const left = compact ? 34 : 44,
    right = width - 14,
    top = 24,
    bottom = height - 27;
  const x = (n: number) => positionX(n, xDomain, left, right);
  const y = (n: number) =>
    bottom - ((n - domain[0]) / (domain[1] - domain[0])) * (bottom - top);
  const ticks = chartTicks(domain, compact ? 2 : 4);
  const tickCount = width < 360 ? 2 : width < 600 ? 3 : 4;
  const xTicks = Array.from(
    { length: tickCount + 1 },
    (_, i) => xDomain[0] + ((xDomain[1] - xDomain[0]) * i) / tickCount,
  );
  const shortTime = (n: number) =>
    new Date(n * 1000).toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      ...(xDomain[1] - xDomain[0] < 600 ? { second: "2-digit" } : {}),
    });
  const nearest =
    selected != null
      ? nearestPoint(primary?.values || [], selected)
      : undefined;
  const selectedX = nearest ? x(nearest.x) : null;
  const selectedValues = nearest
    ? visible.map((s) => ({ ...s, point: nearestPoint(s.values, nearest.x) }))
    : [];
  const selectedIndex = nearest
    ? primary?.values.findIndex((p) => p.x === nearest.x)
    : -1;
  const readable = (n: number | null | undefined) =>
    n == null
      ? "无数据"
      : `${number(n)}${unit === "%" ? "%" : unit ? " " + unit : ""}`;
  const inspect = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    setSelected(
      xDomain[0] +
        Math.max(0, Math.min(1, (px - left) / (right - left))) *
          (xDomain[1] - xDomain[0]),
    );
  };
  const keyboard = (event: React.KeyboardEvent<SVGSVGElement>) => {
    if (event.key === "Escape") {
      setSelected(null);
      return;
    }
    if (
      !primary?.values.length ||
      !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
    )
      return;
    event.preventDefault();
    let i =
      selectedIndex != null && selectedIndex >= 0
        ? selectedIndex
        : primary.values.length - 1;
    i =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? primary.values.length - 1
          : Math.max(
              0,
              Math.min(
                primary.values.length - 1,
                i + (event.key === "ArrowLeft" ? -1 : 1),
              ),
            );
    setSelected(primary.values[i].x);
  };
  const peak = valid.length ? Math.max(...valid.map((p) => p.y)) : null;
  const average = valid.length
    ? valid.reduce((sum, p) => sum + p.y, 0) / valid.length
    : null;
  return (
    <div
      className={`time-chart ${compact ? "time-chart-compact" : ""} ${stale ? "time-chart-stale" : ""}`}
    >
      {series && series.length > 1 ? (
        <div className="chart-legend">
          {visible.map((s) => (
            <span key={s.id}>
              <i
                style={{ color: `var(--${s.color})` }}
                className={s.dashed ? "dashed" : ""}
              />
              {s.name}
              <b>{readable(s.values.at(-1)?.y)}</b>
            </span>
          ))}
        </div>
      ) : null}
      <div className={`chart ${compact ? "compact" : ""}`} ref={root}>
        <svg
          role="img"
          tabIndex={0}
          aria-label={`${label}；${unit ? `单位 ${unit}；` : ""}${valid.length} 个有效样本。左右方向键查看采样点，Escape 返回实时视图。`}
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          onPointerMove={inspect}
          onPointerDown={inspect}
          onPointerLeave={(e) => {
            if (e.pointerType !== "touch") setSelected(null);
          }}
          onKeyDown={keyboard}
          onBlur={() => setSelected(null)}
        >
          <title>{label}</title>
          <desc>
            {valid.length
              ? `最近值 ${readable(primary?.values.at(-1)?.y)}，样本均值 ${readable(average)}，峰值 ${readable(peak)}。`
              : "暂无有效采样，缺失数据不会作为零值绘制。"}
          </desc>
          <defs>
            <clipPath id={`clip-${id}`}>
              <rect
                x={left - 3}
                y={top - 3}
                width={right - left + 6}
                height={bottom - top + 6}
              />
            </clipPath>
            {visible.map((s) => (
              <linearGradient
                id={`${id}-${s.id}`}
                key={s.id}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop
                  offset="0%"
                  stopColor={`var(--${s.color})`}
                  stopOpacity=".15"
                />
                <stop
                  offset="100%"
                  stopColor={`var(--${s.color})`}
                  stopOpacity=".01"
                />
              </linearGradient>
            ))}
          </defs>
          <text className="chart-unit" x={left} y={12}>
            {unit}
          </text>
          {ticks.map((t) => (
            <g key={t}>
              <line
                className="chart-grid"
                x1={left}
                x2={right}
                y1={Math.round(y(t)) + 0.5}
                y2={Math.round(y(t)) + 0.5}
              />
              <text
                className="chart-tick"
                x={left - 9}
                y={y(t)}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {formatTick(t)}
              </text>
            </g>
          ))}
          {allTimes.length
            ? xTicks.map((t, i) => (
                <text
                  className="chart-tick chart-time-tick"
                  key={i}
                  x={x(t)}
                  y={height - 7}
                  textAnchor={
                    i === 0 ? "start" : i === tickCount ? "end" : "middle"
                  }
                >
                  {shortTime(t)}
                </text>
              ))
            : null}
          <g clipPath={`url(#clip-${id})`}>
            {visible.map((s) => {
              const paths = splitPoints(s.values, sampleGap(s.values));
              const last = s.values.at(-1);
              const createLine = line<DefinedPoint>()
                .x((p) => x(p.x))
                .y((p) => y(p.y))
                .curve(curveMonotoneX);
              const createArea = area<DefinedPoint>()
                .x((p) => x(p.x))
                .y0(bottom)
                .y1((p) => y(p.y))
                .curve(curveMonotoneX);
              return (
                <g key={s.id} data-series={s.id}>
                  {paths.map((segment, i) => (
                    <g key={i}>
                      {!s.dashed && segment.length > 1 ? (
                        <path
                          d={createArea(segment) || ""}
                          fill={`url(#${id}-${s.id})`}
                          className="chart-area"
                        />
                      ) : null}
                      <path
                        d={createLine(segment) || ""}
                        fill="none"
                        stroke={`var(--${s.color})`}
                        strokeWidth={compact ? 1.8 : 2.2}
                        strokeDasharray={s.dashed ? "5 4" : undefined}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="chart-series-path"
                      />
                      {segment.length === 1 ? (
                        <circle
                          cx={x(segment[0].x)}
                          cy={y(segment[0].y)}
                          r={2.5}
                          fill={`var(--${s.color})`}
                        />
                      ) : null}
                    </g>
                  ))}
                  {last?.y != null ? (
                    <>
                      <circle
                        cx={x(last.x)}
                        cy={y(last.y)}
                        r={5}
                        fill="var(--panel)"
                      />
                      <circle
                        cx={x(last.x)}
                        cy={y(last.y)}
                        r={3}
                        fill={`var(--${s.color})`}
                      />
                    </>
                  ) : null}
                </g>
              );
            })}
            {nearest && selectedX != null ? (
              <g>
                <line
                  x1={selectedX}
                  x2={selectedX}
                  y1={top}
                  y2={bottom}
                  className="chart-crosshair"
                />
                {selectedValues.map((s) =>
                  s.point?.y != null ? (
                    <circle
                      key={s.id}
                      cx={x(s.point.x)}
                      cy={y(s.point.y)}
                      r={4}
                      fill={`var(--${s.color})`}
                      stroke="var(--panel)"
                      strokeWidth={2}
                    />
                  ) : null,
                )}
              </g>
            ) : null}
          </g>
        </svg>
        {!allValues.length ? (
          <div className="chart-empty">
            <Activity size={18} />
            <span>等待有效采样</span>
            <small>缺失值不会按 0 绘制</small>
          </div>
        ) : null}
        {nearest && selectedX != null ? (
          <div
            className="chart-tooltip"
            role="status"
            style={{
              left: Math.min(width - 180, Math.max(8, selectedX - 80)),
              top: compact ? 8 : 12,
            }}
          >
            <time>{time(nearest.x)}</time>
            {selectedValues.map((s) => (
              <div key={s.id}>
                <span>
                  <i style={{ background: `var(--${s.color})` }} />
                  {series ? s.name : "采样值"}
                </span>
                <b>{readable(s.point?.y)}</b>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      {showSummary ? (
        <div className="chart-summary">
          <span>
            {series ? primary.name + "均值" : "样本均值"}{" "}
            <b>{readable(average)}</b>
          </span>
          <span>
            {series ? primary.name + "峰值" : "峰值"} <b>{readable(peak)}</b>
          </span>
          <span className="chart-updated">
            {stale
              ? "数据已过期"
              : allTimes.length
                ? "更新 " + time(end)
                : "尚无历史数据"}
          </span>
        </div>
      ) : null}
    </div>
  );
}
