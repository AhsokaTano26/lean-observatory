# Static Results Archive Implementation Plan

> Implement inline with test-first verification. Existing worktree isolates this change.

**Goal:** Preserve RH/NS evidence locally and display truthful results without a backend.
**Architecture:** A Python exporter validates captured snapshots and evidence hashes, produces a compact data snapshot and standalone data.js, and copies the current visual theme into a static site with relative evidence links. Generated large logs remain in ignored artifacts; source and compact data are committed.
**Tech Stack:** Python standard library, existing plain HTML/CSS/JavaScript, browser validation.
**Constraints:** No further server access. RH remains incomplete/paused; external verification is attributed separately. NS reports only completed machine checks, semanticReview NOT_RUN. No live counters, external assets, API requests, writes, or admin controls. Large proof/source/toolchain payloads are omitted. Existing theme and responsive behavior are retained.

- [x] Regression tests: RH pause cannot become local pass; NS needs seven successful stages, two audited targets and actual independent acceptance; missing/tampered evidence fails; all file links stay relative.
- [x] Implement exporter and local data capture validation; preserve raw snapshots and full logs.
- [x] Reuse existing UI tokens for project summaries, stages, theorem audits, pinned sources, logs and downloads; offline theme/navigation/search.
- [x] Verify complete dataset, desktop/mobile, file:// and HTTP, no network dependencies/errors/writes, and download integrity.
- [x] Package the portable archive with checksums, commit source/data and push; deliver local preview and archive paths.
