export type Status =
  | "pending"
  | "waiting"
  | "queued"
  | "running"
  | "paused"
  | "passed"
  | "failed"
  | "interrupted"
  | "resource_exhausted"
  | "checks_completed"
  | "cancelled"
  | "not_run";
export interface Stage {
  id: string;
  label: string;
  status: Status;
  startedAt: number | null;
  finishedAt: number | null;
  exitCode: number | null;
}
export interface Audit {
  name: string;
  expectedType: string;
  type: Status;
  axioms: Status;
  replay: Status;
  dependencies: string[];
  output: string | null;
}
export interface Artifact {
  name: string;
  bytes: number;
  sha256: string;
}
export interface Run {
  id: string | null;
  mode: "real" | "mock";
  status: Status;
  phase: string;
  scenario: string;
  startedAt: number | null;
  finishedAt: number | null;
  updatedAt: number;
  elapsedSeconds: number;
  activeSeconds: number;
  workerHeartbeat: number | null;
  error: string | null;
  proofAccepted: boolean;
  overallPercent: number;
  checksPassed: number;
  semanticReview: string;
  independentChecker: string;
  compile: {
    expectedTotal: number;
    total: number | null;
    succeeded: number;
    failed: number;
    remaining: number | null;
    rate: number;
    percent: number;
    etaSeconds: number | null;
    currentModule: string | null;
    jobs: number;
  };
  stages: Stage[];
  audits: Audit[];
  artifacts: Artifact[];
  provenance: {
    url: string;
    expectedSha256: string;
    sha256: string | null;
    expectedBytes: number;
    bytes: number | null;
    hashSource: string;
    integrity: Status;
    inventorySha256: string | null;
  };
  environment: {
    lean: string;
    mathlib: string;
    actualLean: string | null;
    actualMathlib: string | null;
    platform: string | null;
    python: string | null;
  };
  commands: {
    argv: string[];
    cwd: string;
    stage: string;
    startedAt: number;
    finishedAt: number | null;
    exitCode: number | null;
    logFile: string;
  }[];
}
export interface Metrics {
  source: string;
  sampledAt: number | null;
  observedAt?: number;
  stale?: boolean;
  hostname?: string;
  platform?: string;
  cpuCount?: number;
  cpuPercent?: number | null;
  memoryTotalBytes?: number | null;
  memoryUsedBytes?: number | null;
  memoryPercent?: number | null;
  diskTotalBytes?: number;
  diskUsedBytes?: number;
  diskPercent?: number;
  networkRxBytesPerSec?: number | null;
  networkTxBytesPerSec?: number | null;
  load?: number[];
  limitations: string[];
  runId?: string;
  mode?: string;
  rate?: number;
  completed?: number;
}
export interface Log {
  id: number;
  run: string;
  ts: number;
  level: string;
  stage: string;
  message: string;
}
export interface Snapshot {
  run: Run;
  metrics: Metrics;
  serverTime: number;
  workerOnline: boolean;
  capabilities: { readOnly: boolean };
  logs?: Log[];
}
