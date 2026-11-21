# NS successor queue

This add-on preserves the deployed RH stack. It has a separate Compose project, database, systemd controller, AppArmor profile and HTTPS listener on port 9443. The original RH files and containers are never redeployed by the installer.

## Current authorization

The owner authorizes a shared **20-hour server clock** from **2026-11-21T14:42:36Z** to **2026-11-22T10:42:36Z** (Beijing18:42:36). RH, idle and NS time all count from rental, without resetting at service restart or NS handoff.

Latest policy is `notify_only`: RH necessary machine checks and complete durable evidence must succeed, then NS automatically starts. Remaining time and available-resource preflight only warn; they do not prevent or stop NS. Alerts are sent at1h/15m remaining and expiry. At expiry both jobs are left to the owner's decision, with continued server billing. No automatic shutdown or deletion is configured. USD3.36/hour is an auxiliary estimate, not provider credit or a spending ceiling. Fresh installations still initialize to0 hours until this policy and a rental start are explicitly configured.

The UI is GET-only. Host CLI operations are not exposed publicly.

## Isolation and evidence

- `/opt/lean-observatory-ns`: additive deployment; `/var/lib/lean-observatory-queue`: durable SQLite WAL queue, events, alerts, checkpoints and evidence.
- Light services: API 0.10 CPU/96 MiB, Nginx 0.10 CPU/32 MiB, controller 0.05 CPU/128 MiB. No existing RH service restart or Nginx reload.
- Future NS worker: separate image, 60 vCPU, CPUs 4–63, 250 GB decimal (232.83 GiB), no swap; no Docker socket or RH mounts. It only starts after fresh RH success, matching durable report/log hashes, no other active verification, and the configured startup policy. In notify_only mode, time/resource preflight only warns. Legacy hard mode requires a five-minute reserve.
- The controller rechecks RH after evidence persistence and again after image build immediately before worker creation or resume. A deterministic container name, owner labels and exclusive controller lock prevent duplicate launches. Completed stages are skipped only if source, implementation, prior checkpoint and recorded output hashes still match.
- Explicit RH failure or a stopped RH worker pauses NS and preserves logs. A stale heartbeat alone is not proof of RH failure. Temporary API loss keeps the queue blocked; API loss plus a stopped RH worker pauses it.
- Notifications use a persistent deduplicated outbox. HTTP 200 means confirmed send; HTTP 202 means queued by the webhook and awaiting delivery, with no false delivery claim. Non-success responses retry with backoff.

## Fixed NS scope

Repository: https://github.com/openai/NavierStokesAndEuler/tree/f9e8bc5b38b6e212696e8a30e3e91517af887bbd

The complete source archive is 6,535,449 bytes, SHA-256 `8ac9b0b2db70385f1e466b6ad600476dcad62d687d78a38f24fd1e8662bd04a0`. `ns_queue/manifest.json` pins Lean `v4.34.0-rc2`, Mathlib, Comparator, exporter and external checker snapshots independently of RH. Original dependency configuration is preserved and checked.

All 2,659 repository Lean files are included in the default library build (including Euler). Final NS type/axiom/kernel/independent checks use `NavierStokes.ComparatorSolution` and the two `NavierStokes.Comparator.navier_stokes_breakdown_*` claims. This does not claim an independent audit of Euler or a proof of any unforced classical Millennium Problem formulation. The four exact challenge reference `sorry` lines are allowed only at pinned paths, whole-file hashes and lines, never in the audited solution import closure. Additional axioms including `sorryAx` and `Lean.trustCompiler` block acceptance.

The seven stages are source, dependencies, compile, audit, fresh kernel replay, independent Comparator/nanoda verification, and result persistence. Real subprocess exit codes, full raw logs and hashes drive progress. Independent tool compatibility and Linux sandbox enforcement are pending actual execution. Missing/incompatible tools or an unenforced sandbox block the stage. `CHECKS_COMPLETED` means the listed machine checks completed; `proofAccepted` remains false pending separate mathematical review.

## Reproduce local checks

```sh
python3 -m unittest discover -s tests -q
node --test tests/chart-math.test.ts
node --test tests/ns-addon-browser.test.mjs
npm run build
npm run test:e2e
```

The NS browser test uses only a local queued fixture and tests 1440, 390 and 320 px layouts, theme persistence, log filtering, GET-only traffic and SSE reconnection after server restart. Browser plugin is unavailable; Playwright is used. Deployment requires `reports/ns-local-acceptance.json` with a matching add-on source fingerprint and successful unit, browser, Compose and compile checks. The immutable receipt proves local platform checks, not a completed NS proof verification.

## Install and operate

The first-install script defaults to a dry run and refuses stale acceptance, pre-existing add-on state or any installation path other than `/opt/lean-observatory-ns`. It reuses existing TLS certificates read-only. Add DNS/firewall handling only if necessary without replacing existing rules. There is no automatic RH migration.

```sh
cd /opt/lean-observatory-ns
python3 deploy/ns/install.py
python3 deploy/ns/install.py --execute
python3 -m ns_queue.control --root /var/lib/lean-observatory-queue status
```

Page: `https://lean.tano.asia:9443/ns/` (also `lean.lanunion.org.cn:9443`). The original RH page remains on port 443. Only the new certificate-path watcher may reload the new Nginx after certificate renewal.

Configure the confirmed shared window on the host:

```sh
python3 -m ns_queue.control --root /var/lib/lean-observatory-queue set-budget --hours 20 --started-at 2026-11-21T14:42:36+00:00 --mode notify-only
```

The rental origin locks once set. Repeating the same settings is idempotent and does not reset time. `resume` is only needed for a genuinely paused/failed NS job; the current QUEUED job follows RH automatically. Lost launch acknowledgement and service restart adopt the same deterministic NS container. Failed mandatory proof/tool checks still preserve logs and pause; no result is fabricated.

Both RH and NS are configured for60vCPU and250000000000 bytes (250GB decimal), cpuset4-63, no swap. RH live resizing uses `deploy/ns/update_resources.py --expected-id ... --execute`; it checks identity and uses only `docker update`, preserving PID/start/image/command/mounts. It saves `/opt/lean-observatory/.data/ops/compose.resources.runtime.yaml` for future Compose recreations. The current RH compiler process keeps its original48-thread scheduler, while resource ceilings become60 and new tasks/NS use60 threads. Updating the ceilings does not rebuild/restart the running RH image.

Shared host metrics, per-NS Docker usage, elapsed rental hours and costs remain distinct. NS estimated cost is0 until its own start; total server cost includes the rental interval. Unavailable measurements display as unknown.
