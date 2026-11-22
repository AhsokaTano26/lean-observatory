# NS successor queue

This add-on preserves the deployed RH stack. It has a separate Compose project, database, systemd controller, AppArmor profile and a shared HTTPS route at /ns/. The original RH files and containers are never redeployed by the installer.

## Current authorization

The owner authorizes a shared **20-hour server clock** from **2026-11-21T14:42:36Z** to **2026-11-22T10:42:36Z** (Beijing18:42:36). RH, idle and NS time all count from rental, without resetting at service restart or NS handoff.

The owner additionally authorizes NS to run during RH's pending kernel replay. This explicit `schedulingMode: parallel_replay` records a `parallelAdmission` replay snapshot with run identity, timestamp, file path, SHA-256, byte count and `finalSuccess: false`. The snapshot admits overlap; it is not final RH success evidence. `rhEvidence.persisted` remains false until RH's real required checks succeed and their final evidence is archived. During overlap NS has 60 vCPU and 220000000000 bytes (220 GB decimal); its recorded `resourceProfile` changes to 250000000000 bytes only after actual RH success and the resource promotion. The NS detail page displays that current profile, the pending RH replay and NS's parallel status. The project entrance remains minimal and shows the two actual task statuses without additional fine print.

The unchanged default is serial: RH necessary machine checks and complete durable evidence must succeed, then NS automatically starts. The server policy is `notify_only`: remaining time and available-resource preflight only warn; they do not prevent or stop NS. Alerts are sent at1h/15m remaining and expiry. At expiry both jobs are left to the owner's decision, with continued server billing. No automatic shutdown or deletion is configured. USD3.36/hour is an auxiliary estimate, not provider credit or a spending ceiling. Fresh installations still initialize to0 hours until this policy and a rental start are explicitly configured.

The UI is GET-only. Host CLI operations are not exposed publicly.

## Isolation and evidence

- `/opt/lean-observatory-ns`: additive deployment; `/var/lib/lean-observatory-queue`: durable SQLite WAL queue, events, alerts, checkpoints and evidence.
- Light services: API 0.10 CPU/96 MiB, Nginx 0.10 CPU/32 MiB, controller 0.05 CPU/256 MiB (`GOMAXPROCS=2`, 128 tasks; Docker CLI plugins need bounded Go runtime concurrency). RH verification/API are not restarted; the router is gracefully reloaded when routes change.
- NS worker: separate image, 60 vCPU, CPUs 4–63, no swap; no Docker socket or RH mounts. Default serial admission requires fresh RH success, matching durable report/log hashes, no other active verification, and the configured startup policy, with a 250 GB decimal (232.83 GiB) limit. The explicitly authorized RH replay overlap instead uses the recorded replay admission and a 220 GB limit until promotion. In notify_only mode, time/resource preflight only warns. Legacy hard mode requires a five-minute reserve.
- The controller rechecks RH after evidence persistence and again after image build immediately before worker creation or resume. A deterministic container name, owner labels and exclusive controller lock prevent duplicate launches. Completed stages are skipped only if source, implementation, prior checkpoint and recorded output hashes still match.
- Network-enabled dependency preparation allows local Unix resolver sockets needed by Cargo/libcurl. Offline proof commands and Comparator wrappers retain the AF_UNIX seccomp filter; real Linux negative tests verify denial and that nested preparation mode cannot remove an inherited filter.
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
node --test tests/ns-parallel-browser.test.mjs
npm run build
npm run test:e2e
```

The original NS browser test uses only a local queued fixture and tests 1440, 390 and 320 px layouts, theme persistence, log filtering, GET-only traffic and SSE reconnection after server restart. A separate parallel-admission fixture checks pending RH replay, parallel NS status, the 220 GB allocation, the later recorded 250 GB promotion, the minimal entrance, and GET-only traffic at 1440 and 390 px. Browser plugin is unavailable; Playwright is used. Deployment requires `reports/ns-local-acceptance.json` with a matching add-on source fingerprint and successful unit, browser, Compose and compile checks. The immutable receipt proves local platform checks, not a completed NS proof verification.

## Install and operate

The first-install script defaults to a dry run and refuses stale acceptance, pre-existing add-on state or any installation path other than `/opt/lean-observatory-ns`. It reuses existing TLS certificates read-only. Add DNS/firewall handling only if necessary without replacing existing rules. There is no automatic RH migration.

```sh
cd /opt/lean-observatory-ns
python3 deploy/ns/install.py
python3 deploy/ns/install.py --execute
python3 -m ns_queue.control --root /var/lib/lean-observatory-queue status
```

Project entrance: `https://lean.tano.asia/`; RH: `https://lean.tano.asia/rh/`; NS: `https://lean.tano.asia/ns/` (same paths on `lean.lanunion.org.cn`). Both projects use80/443, HTTP redirectsHTTPS, and9443 is not published. Only the new certificate-path watcher may reload the new Nginx after certificate renewal.

Configure the confirmed shared window on the host:

```sh
python3 -m ns_queue.control --root /var/lib/lean-observatory-queue set-budget --hours 20 --started-at 2026-11-21T14:42:36+00:00 --mode notify-only
```

Before the first NS launch, the host-only command `python3 -m ns_queue.control --root /var/lib/lean-observatory-queue set-scheduling --mode parallel-replay` explicitly authorizes replay overlap; scheduling authorization locks after a task starts.

The rental origin locks once set. Repeating the same settings is idempotent and does not reset time. `resume` is only needed for a genuinely paused/failed NS job; the current QUEUED job follows RH automatically. Lost launch acknowledgement and service restart adopt the same deterministic NS container. Failed mandatory proof/tool checks still preserve logs and pause; no result is fabricated.

The default RH and NS profiles are60vCPU and250000000000 bytes (250GB decimal), cpuset4-63, no swap; the authorized pending-RH overlap temporarily gives NS220000000000 bytes as described above. RH live resizing uses `deploy/ns/update_resources.py --expected-id ... --execute`; it checks identity and uses only `docker update`, preserving PID/start/image/command/mounts. It saves `/opt/lean-observatory/.data/ops/compose.resources.runtime.yaml` for future Compose recreations. The current RH compiler process keeps its original48-thread scheduler, while resource ceilings become60 and new tasks/NS use60 threads. Updating the ceilings does not rebuild/restart the running RH image.

Shared host metrics, per-NS Docker usage, elapsed rental hours and costs remain distinct. NS estimated cost is0 until its own start; total server cost includes the rental interval. Unavailable measurements display as unknown.

Shared routing is activated with `deploy/ns/activate_proxy.py --execute`: validate candidate using the existing trusted Nginx image and certificates, keep a backup, write the mounted config in place, graceful reload then attach the NS network. Full container hostnames avoid conflicting Docker `api` aliases; failed activation restores the previous config/network. `/api` and `/assets` remain RH compatibility paths, while NS uses only `/ns/api` and `/ns/assets`. Root entrance assets are served from the NS namespace. The network override is saved at `/opt/lean-observatory/.data/ops/compose.ns-route.runtime.yaml` for future router recreations.

### Landlock ABI 4 compatibility repair (2026-11-22)

The `landlock_not_enforced` interruption occurred after the actual write-denial
probe exited zero: the worker incorrectly rejected every native Landrun warning.
The repaired worker accepts only the exact pinned tool's ABI 4 feature warning,
and only after an isolated Python probe verifies the actual filesystem denial,
unprivileged UID/GID, zero capabilities, no-new-privileges, seccomp, private PID
root and network, both AF_UNIX denials, no routes, denied IPv4/IPv6 TCP/UDP,
no user namespace creation, and a limited device/inherited descriptor set.
Unknown warnings, failed guards, missing acceptance markers and nonzero command
exits still block acceptance. Raw warnings remain in logs and the final report.

The profile is `landlock+namespaces+seccomp`. It does not claim native ABI 5+
features: ioctl is not disabled (only null/urandom devices and pipe/null inherited
fds are available), and signal isolation is supplied by a private PID namespace,
not Landlock domain scoping. See the [kernel Landlock ABI documentation](https://docs.kernel.org/userspace-api/landlock.html).

For this reviewed repair, `python3 -m ns_queue.audit_migration --repair independent-policy`
validates the paused queue without modifying it; `--execute` commits only after
all original output bytes, the two previous migration ledgers, and the exact
approved policy hash verify. The five successful stages are retained, with
original/proposed receipt bytes and the third migration ledger durably saved.
Do not delete successful checkpoints or restart RH to apply this repair.
`tests/ns-sandbox-policy.test.mjs` uses real Linux Landlock/namespace/seccomp
controls and rejects removed filesystem or socket restrictions. The deployment
also runs the pinned server Landrun probe before committing the migration.
