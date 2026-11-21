export const number = (n: number | null | undefined) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(n);
export function duration(s: number | null | undefined) {
  if (s == null) return "—";
  const n = Math.max(0, Math.round(s));
  return [Math.floor(n / 3600), Math.floor((n % 3600) / 60), n % 60]
    .map((x) => String(x).padStart(2, "0"))
    .join(":");
}
export function bytes(n: number | null | undefined) {
  if (n == null) return "—";
  if (n < 1024) return `${number(n)} B`;
  const i = Math.min(4, Math.floor(Math.log(n) / Math.log(1024)));
  return `${number(n / 1024 ** i)} ${["B", "KiB", "MiB", "GiB", "TiB"][i]}`;
}
export const time = (n: number | null | undefined) =>
  n ? new Date(n * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "—";
export const statusLabels: Record<string, string> = {
  pending: "待检查",
  waiting: "等待任务",
  queued: "排队中",
  running: "运行中",
  paused: "已暂停",
  passed: "已完成",
  failed: "失败",
  interrupted: "已中断",
  resource_exhausted: "资源不足",
  checks_completed: "检查已完成",
  cancelled: "已取消",
  not_run: "未执行",
};
