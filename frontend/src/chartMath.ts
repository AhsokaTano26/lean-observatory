export interface ChartPoint {
  x: number;
  y: number | null | undefined;
}
export interface DefinedPoint {
  x: number;
  y: number;
}

import type { Metrics } from "./types";
export function chartSample(sample: Metrics): Metrics {
  if (!sample.stale) return sample;
  return {
    ...sample,
    sampledAt: sample.observedAt ?? sample.sampledAt,
    cpuPercent: null,
    memoryPercent: null,
    memoryUsedBytes: null,
    diskPercent: undefined,
    diskUsedBytes: undefined,
    networkRxBytesPerSec: null,
    networkTxBytesPerSec: null,
    load: undefined,
  };
}

export function normalizePoints(points: ChartPoint[]): ChartPoint[] {
  const samples = new Map<number, ChartPoint>();
  for (const p of points)
    if (Number.isFinite(p.x))
      samples.set(p.x, {
        x: p.x,
        y: p.y != null && Number.isFinite(p.y) ? p.y : null,
      });
  return [...samples.values()].sort((a, b) => a.x - b.x);
}

export function positionX(
  value: number,
  domain: [number, number],
  left: number,
  right: number,
) {
  return (
    left +
    ((value - domain[0]) / Math.max(0.001, domain[1] - domain[0])) *
      (right - left)
  );
}

export function chartDomain(values: number[], max?: number): [number, number] {
  if (max != null && max > 0) return [0, max];
  const peak = Math.max(0, ...values.filter(Number.isFinite));
  if (!peak) return [0, 1];
  const target = (peak * 1.08) / 4;
  const power = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 2.5, 5, 10]
    .map((x) => x * power)
    .find((x) => x >= target)!;
  return [0, Math.ceil((peak * 1.02) / step) * step];
}

export function chartTicks(domain: [number, number], count = 4) {
  return Array.from(
    { length: count + 1 },
    (_, i) =>
      +(domain[0] + ((domain[1] - domain[0]) * i) / count).toPrecision(12),
  );
}

export function formatTick(n: number): string {
  const fmt = (x: number) =>
    new Intl.NumberFormat("en-US", {
      maximumFractionDigits: Math.abs(x) < 1 ? 2 : Math.abs(x) < 10 ? 1 : 0,
    }).format(x);
  if (Math.abs(n) >= 1e6) return fmt(n / 1e6) + "M";
  if (Math.abs(n) >= 1e3) return fmt(n / 1e3) + "k";
  return fmt(n);
}

export function splitPoints(
  points: ChartPoint[],
  maxGap = Infinity,
): DefinedPoint[][] {
  const segments: DefinedPoint[][] = [];
  let current: DefinedPoint[] = [];
  for (const point of points) {
    if (point.y == null || !Number.isFinite(point.y)) {
      if (current.length) segments.push(current);
      current = [];
      continue;
    }
    if (current.length && point.x - current[current.length - 1].x > maxGap) {
      segments.push(current);
      current = [];
    }
    current.push({ x: point.x, y: point.y });
  }
  if (current.length) segments.push(current);
  return segments;
}

export function nearestPoint(
  points: ChartPoint[],
  x: number,
): ChartPoint | undefined {
  if (!points.length) return undefined;
  let low = 0,
    high = points.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (points[mid].x < x) low = mid + 1;
    else high = mid;
  }
  return low > 0 &&
    Math.abs(points[low - 1].x - x) < Math.abs(points[low].x - x)
    ? points[low - 1]
    : points[low];
}

export function sampleGap(points: ChartPoint[]) {
  const steps = points
    .slice(1)
    .map((p, i) => p.x - points[i].x)
    .filter((x) => x > 0)
    .sort((a, b) => a - b);
  // Host sampling is 5 s; a long outage must not redefine that cadence.
  const cadence = steps[Math.floor((steps.length - 1) / 2)] || 5;
  return Math.max(15, Math.min(30, cadence * 4));
}

export function mergeSamples<T extends { sampledAt: number | null }>(
  old: T[],
  incoming: T[],
  limit = 1801,
): T[] {
  const samples = new Map<number, T>();
  for (const sample of [...old, ...incoming]) {
    if (sample.sampledAt == null || !Number.isFinite(sample.sampledAt))
      continue;
    const key = Math.floor(sample.sampledAt),
      existing = samples.get(key);
    if (!existing || (existing.sampledAt || 0) <= sample.sampledAt)
      samples.set(key, sample);
  }
  return [...samples.values()]
    .sort((a, b) => (a.sampledAt || 0) - (b.sampledAt || 0))
    .slice(-limit);
}
