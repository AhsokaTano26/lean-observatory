import { execFileSync } from "node:child_process";
const data = "/tmp/lean-observatory-e2e";
export function hostControl(...args: string[]) {
  return JSON.parse(
    execFileSync(
      "python3",
      ["-m", "backend.control", "--data", data, ...args],
      { encoding: "utf8" },
    ),
  );
}
export function resetMock() {
  for (const run of hostControl("list")) {
    if (
      [
        "running",
        "queued",
        "paused",
        "failed",
        "interrupted",
        "resource_exhausted",
      ].includes(run.status)
    )
      hostControl("cancel", run.id);
  }
}
export function startMock(scenario = "success") {
  return hostControl("create", "--mode", "mock", "--scenario", scenario);
}
