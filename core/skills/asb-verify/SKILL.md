---
name: asb-verify
description: Use when the module is built and the client or consultant wants it tested, verified, checked against the acceptance tests, or asks whether it is ready; also to run the fix loop after a failed verification.
---

# Stage 5: Verify

**Purpose:** produce evidence that the build meets the approved design, fix what fails (at most 3 rounds), and get an independent review.

**Inputs:** the built app, `design/acceptance.md`.

## Steps

1. `asb gate <name> verify` must print `OK` (build done, design unchanged since approval, fewer than 3 verify rounds used).
2. `asb verify <name>`. It runs every automated check the pack provides (typically acceptance mapping, tests, permission and workflow matrices, reports, static checks, build and UI smoke; a check that cannot run is reported as skipped with a reason) and writes `verify-report.md`.
3. Read `solutions/<name>/verify-report.md`: the table, **Failures**, **Skipped**, and the final Result line.
4. On failure, fix the cause in AI-owned files only (see asb-build; change `solution.yaml` only via the design stage), run `asb check <name>`, then `asb verify <name>` again. Each run is one round; `asb status <name>` shows `verify_rounds`. The gate refuses a fourth run: stop and escalate to a human with the failing checks, what you tried and your suspected cause. Rebuilding the same design does not reset the count; only a newly approved design does. Never raise the limit or edit `status.json`.
5. After a passing verify, dispatch the **asb-reviewer** agent for an independent review. It writes `solutions/<name>/review.md`. Read it and fix Critical and Important findings that are in scope (this may need another verify round).
6. Summarise for the human: result, what each check proved, skipped checks and why, reviewer findings by severity, open risks. Be honest about skips; a skip is not a pass.

## Outputs

`verify-report.md`, `review.md`; stage 5 marked done by a passing `asb verify`.

## Gate

All checks pass and a human accepts the report and the review. The reviewer is advisory only.

## Boundaries

- Never run `asb approve` or `asb use`; ask the human to.
- Do not weaken or delete a test to make it pass.
- Report failures as they are.
