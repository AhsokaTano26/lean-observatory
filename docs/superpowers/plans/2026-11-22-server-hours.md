# Shared Server Hours Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task.

**Goal:** Track and display the user's single20h server window without touching RH.
**Architecture:** Pure hour/deadline model shared by host controller, driver, worker, API and CLI; migrate only own queue. Public UI remains read-only.
**Tech Stack:** Existing Python/SQLite/SSE/Docker addon.
**Spec:** ../specs/2026-11-22-server-hours-design.md

## Global Constraints
- Fixed rental start2026-11-21T14:42:36Z and20h => deadline2026-11-22T10:42:36Z.
- No RH changes or stopping; user decides at deadline. No host shutdown/deletion.
- Production notify_only policy: RH barrier remains mandatory; time/resource preflight warn without blocking; at expiry notify and continue. Legacy hard mode still tests300s reserve.
- No new dependencies or heavy NS verification during local testing/deploy.

## Review Focus
- Rental time includes RH/idle, queue or service restart never resets clock.
- Nonfinite, naive/future/changed rental starts cannot grant runtime.
- USD rate is informational; hour authorization remains fixed.
- Expired queued tasks still alert; owned running NS stops only its own container.
- Existing notification receipts and task identity survive upgrade.

### Task1: Model, CLI, all runtime gates
- [x] Write tests/test_ns_budget.py for shared window, legacy0 conversion, rate independence, expiry, restart, CLI start invariance; observe RED.
- [x] Implement normalize(budget,now=None), available_seconds(budget,now=None), runtime_usage(budget,hours,now=None) in ns_queue/budget.py; wire store/control/gates/controller/driver/ns_worker.
- [x] Controller tests for1h/15m/expiry notices while RH runs, legacy owned NS stop, and notify_only automatic handoff after expiry; verify GREEN.

### Task2: Read-only display and local acceptance
- [x] Extend API/browser checks for20h total, used/remaining/deadline, distinct NS cost and GET-only traffic; observe RED then change web.py/web assets.
- [x] Update operations docs; run exact-source local_acceptance.py (full unit/charts/RH browser/NS browser/build/compose/compile), independent review.
- [x] Local gitcommit then push; package exact accepted source.

### Task3: Addon-only deploy
- [x] Record fresh RH identities/config hashes and external9443 check.
- [x] Update only own addon; CLI set-budget --hours20 --started-at2026-11-21T14:42:36+00:00 --mode notify-only; restart only NS services.
- [x] Verify public HTTPS, real20h deadline, NSqueued, notice delivery, RH unchanged/counters increasing. Save report, commit/push and synchronize workspace.

### Resource update
- [x] Test RH docker update identity preservation; validate both Compose profiles60vCPU/250000000000bytes/cpuset4-63.
- [x] After local receipt+commit/push, apply tested update_resources.py to exact original RH containerID, without stopping/recreating it; save runtime Compose override and evidence.
- [x] Preserve running RH48-thread Lake command and all artifacts; new tasks/NS scheduler default60.
