import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizePoints,
  chartDomain,
  formatTick,
  splitPoints,
  nearestPoint,
  positionX,
  chartTicks,
  sampleGap,
  mergeSamples,
} from "../frontend/src/chartMath.ts";

test("normalize preserves missing measurements, sorts times and deduplicates snapshots", () => {
  assert.deepEqual(
    normalizePoints([
      { x: 30, y: 9 },
      { x: 10, y: 2 },
      { x: 20, y: null },
      { x: 30, y: 4 },
      { x: NaN, y: 3 },
    ]),
    [
      { x: 10, y: 2 },
      { x: 20, y: null },
      { x: 30, y: 4 },
    ],
  );
});
test("time spacing reflects elapsed time rather than sample order", () => {
  assert.equal(positionX(10, [0, 100], 0, 500), 50);
  assert.equal(positionX(90, [0, 100], 0, 500), 450);
});
test("domains use calm readable bounds and preserve percent scale", () => {
  assert.deepEqual(chartDomain([32, 58, 71], 100), [0, 100]);
  assert.deepEqual(chartTicks([0, 100], 4), [0, 25, 50, 75, 100]);
  assert.deepEqual(chartDomain([33, 47]), [0, 60]);
  assert.deepEqual(chartDomain([6400, 7100]), [0, 8000]);
  assert.deepEqual(chartDomain([0, 0]), [0, 1]);
});
test("axis labels are compact, no fractional large-rate noise", () => {
  assert.equal(formatTick(7500), "7.5k");
  assert.equal(formatTick(50), "50");
  assert.equal(formatTick(0.25), "0.25");
});
test("missing data and outages break paths instead of spanning the gap", () => {
  const points = [
    { x: 0, y: 2 },
    { x: 1, y: 3 },
    { x: 2, y: null },
    { x: 3, y: 4 },
    { x: 100, y: 5 },
  ];
  assert.deepEqual(
    splitPoints(points, 10).map((s) => s.map((p) => p.x)),
    [[0, 1], [3], [100]],
  );
});
test("pointer inspection picks nearest timestamp including null", () => {
  assert.deepEqual(
    nearestPoint(
      [
        { x: 0, y: 2 },
        { x: 20, y: null },
        { x: 80, y: 5 },
      ],
      21,
    ),
    { x: 20, y: null },
  );
  assert.equal(nearestPoint([], 20), undefined);
});

test("a sparse outage cannot become the inferred sampling cadence", () => {
  const points = [
    { x: 0, y: 2 },
    { x: 5, y: 3 },
    { x: 605, y: 4 },
  ];
  assert.deepEqual(
    splitPoints(points, sampleGap(points)).map((s) => s.map((p) => p.x)),
    [[0, 5], [605]],
  );
});

test("one-second history retains the full thirty-minute selectable window", () => {
  const points = Array.from({ length: 2000 }, (_, i) => ({ sampledAt: i }));
  const retained = mergeSamples([], points);
  assert.ok(retained.at(-1)!.sampledAt - retained[0].sampledAt >= 1800);
});

test("live and polled history merge without duplicate points or losing newer samples", async () => {
  const { mergeSamples } = await import("../frontend/src/chartMath.ts");
  const result = mergeSamples(
    [
      { sampledAt: 100.9, value: 4 },
      { sampledAt: 101, value: 5 },
    ],
    [
      { sampledAt: 100.2, value: 1 },
      { sampledAt: 102, value: 6 },
    ],
  );
  assert.deepEqual(
    result.map((s) => s.value),
    [4, 5, 6],
  );
});

test("stale history breaks every resource trace without discarding real compile progress", async () => {
  const { chartSample } = await import("../frontend/src/chartMath.ts");
  const stale = {
    source: "host_agent",
    sampledAt: 100,
    observedAt: 140,
    stale: true,
    cpuPercent: 70,
    memoryPercent: 20,
    diskPercent: 40,
    diskUsedBytes: 999,
    networkRxBytesPerSec: 45,
    networkTxBytesPerSec: 4,
    load: [2, 3, 4],
    rate: 42,
    limitations: [],
  };
  const masked = chartSample(stale);
  assert.equal(masked.sampledAt, 140);
  assert.equal(masked.cpuPercent, null);
  assert.equal(masked.diskPercent, undefined);
  assert.equal(masked.diskUsedBytes, undefined);
  assert.equal(masked.rate, 42);
  assert.equal(stale.diskUsedBytes, 999);
});
