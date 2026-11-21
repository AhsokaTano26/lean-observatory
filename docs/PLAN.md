# Lean Observatory — design and execution plan

The user explicitly requested autonomous implementation and sequential gates. No remote connection before the local gate. Server does not exist yet; hostname is expected to be lean.tano.asia. Work occurs in this initially empty workspace.

## Design
React/TypeScript/Vite, Python standard-library HTTP/SSE API, SQLite WAL for state, bounded API log windows with full append-only command logs on disk, a separate single-worker scheduler, Linux /proc metrics collected by a separate agent. Dark navy/cyan scientific operations console, light theme, responsive sidebar and panels. Six navigable views: overview, compilation, server, audit, timeline, results. Explicit Mock provenance on every view/report. Native status semantics: waiting/running/paused/interrupted/resource_exhausted/failed/checks_completed. No automatic mathematical-proof acceptance claim. Semantic review remains pending.

Alternatives considered: full Node backend (adds dependencies for OS/process monitoring), single Python-rendered app (less robust UI state). Chosen React + standard-library Python makes task controls/persistence inspectable and limits runtime dependencies. This is an implementation choice delegated by the user.

## Ordered work
1. Write failing backend tests for accounting, audit fail-closed logic, persistence, mock success/failure/interruption/resume/resource scenarios, safe archive extraction/hash/size validation, command exit codes, API/SSE and authentication.
2. Implement backend data model/store, metrics, SSE/REST, mock engine. Worker must consume jobs independently of API process. Persist events, history, logs, artifact manifests.
3. Implement six views and theme/navigation/log search/download/task controls; all displayed measurements have backend fields and explicit null/unsupported states.
4. Implement pinned real verification pipeline: 14 original parts, expected bytes/hash, bounded extraction, source inventory and per-file hashes, unchanged lakefile and manifest/toolchain, dependency preparation, all source compilation, exact theorem type checks and transitive axiom allowlist, leanchecker fresh replay. Distinct optional independent checker stays not_run. Command exit code and artifacts control outcomes. No source cache for original project.
5. Prepare Compose/Nginx TLS, quotas, host metric agent, token-auth task controls, volumes, health checks, preflight scripts, local gate receipt and deploy gate.
6. Run backend suite, TypeScript/build, browser desktop/mobile/light/dark/scenario/connection tests. Record commands, screenshots, and local report; include Docker runtime if accessible. Fix defects and rerun affected checks.
7. Only after complete local gate, inspect remote when purchased and SSH target supplied. Deploy/retest first, then launch full verification. Long-running jobs remain running until real evidence finishes.

## Review focus
Wrong HTML HTTP-200 download, traversal/symlink archive, unexpected axioms or missing output, build progress incorrectly counting C facets/dependencies, process restart/resume, stale metrics, SSE replay gaps, unauthorized mutations, interrupted command exit codes, never converting mock success to real success.

## Current blockers
Remote machine not purchased. Docker socket access currently denied in this session, so Compose runtime acceptance cannot yet be claimed. We can still build/test native local services and validate Compose structurally.
