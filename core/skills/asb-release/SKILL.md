---
name: asb-release
description: Use when a verified module is ready to go to the client, or someone asks about UAT, client sign-off, staging, backup, rollback, deployment or go-live for a solution.
---

# Stage 6: Release (manual runbook only)

**Release automation is sub-project 3 and is not built.** `asb` has no deploy command today. This skill gives the checklist a person follows; you help prepare the material and track the steps, but you do not deploy anything.

`asb gate <name> release` currently checks only that verify is done and a `client` approval is recorded.

## Steps

1. Confirm `asb status <name>` shows verify done and review the latest `verify-report.md` and `review.md`.
2. Prepare a change summary for the client in `solutions/<name>/release/change-summary.md`: what the module does, roles, acceptance tests passed, known limitations and open risks (from `design-review.md` and `review.md`).
3. **UAT checklist** (the client runs it on a staging copy; record who, when, pass/fail per item):
   - each role can log in and sees only what it should,
   - every acceptance test scenario in `acceptance.md` is walked by a real user,
   - each workflow transition works and is refused for the wrong role,
   - each report returns the expected rows for known data,
   - data read from the client's system matches what users see there,
   - error cases (system unavailable, refused action) show a clear message.
4. **Client approval:** when UAT is signed off, ask the human to run `asb approve <name> client --by "<client contact>"`.
5. **Backup checklist** (before any deployment): full backup of the target database and uploaded files; restore tested on a spare copy; backup location and time recorded; configuration and environment variables captured (names only, never values).
6. **Rollback checklist:** the previous version is tagged and deployable; steps to stop the new version, restore the backup and restart the old one are written down and were rehearsed on staging; owner and decision time-limit named; client told how to report problems.
7. **Go-live approval:** after staging works and backup and rollback are ready, ask the human to run `asb approve <name> golive --by "<name>"`.
8. A person deploys by hand and records the deployment log and result.

## Outputs

Draft change summary and checklists under `solutions/<name>/release/`; approvals recorded by the human.

## Gate

**Client approval** before staging; **go-live approval** before production. Both are human decisions.

## Boundaries

- Never run `asb approve` or `asb use`; ask the human to.
- Do not claim anything was deployed, backed up or rolled back unless a person confirms it.
