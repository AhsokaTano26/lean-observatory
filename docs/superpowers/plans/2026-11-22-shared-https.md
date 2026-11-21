# Shared HTTPS Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task.

**Goal:** RH at `/`, NS at `/ns/`, only80/443 public.
**Architecture:** Existing RH Nginx graceful route patch; independent NSAPI and data preserved.
**Tech Stack:** Existing Python/Docker/Nginx/SSE.
**Spec:** ../specs/2026-11-22-shared-https-design.md

- [x] RED namespace API/assets/links tests; implement `/ns/` base-relative frontend and prefix-aware backend.
- [x] RED proxy patch/safeguard tests; implement candidate validation, original-config backup, graceful reload and unique-host network attachment; never restartRHworker/API.
- [ ] Local real Nginx integration forRH/NS route isolation, assets, SSE, downloads andHTTPredirect; test no published9443; full local acceptance and review.
- [ ] Commit/push, freshRHbaseline, deploy onlyNSimage and router patch, verify443 before removing9443 publication.
- [ ] Verify publicbothdomains and preservedRHprocess/progress, persistreport, commit/push/syncworkspace.

Latest UI direction: remove all small entry copy, retain names/status/progress/links/timing with >=16px visible type. Stage deployment: upNSapi only; patch/reload sharedrouter; verify443; recreate onlyNSnginx toremove9443 publication. RHworker/API mustnotrecreate.
