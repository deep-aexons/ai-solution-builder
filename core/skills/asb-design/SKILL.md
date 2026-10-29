---
name: asb-design
description: Use when requirements are approved (and discovery is reviewed) and the client wants a solution design, process map, data model, workflow, roles, business rules, acceptance tests or an implementation plan before building.
---

# Stage 3: Solution design

**Purpose:** produce the design package a human approves. Nothing is built until the approved model's hash is recorded.

**Inputs:** approved `requirements.md`, `discovery.md`, the pack's capabilities (`packs/<pack>/pack.yaml`).

## Steps

1. `asb gate <name> design` must print `OK` (requirements approved). If it refuses, stop and ask the human to approve requirements.
2. Write the five files under `solutions/<name>/design/` (worked example: `solutions/gate-pass/design/`):
   - `process-map.md`: a Mermaid flowchart of the process and who acts at each step.
   - `solution.yaml`: the model. Keys: `solution`, `version`, `description`, `external` (neutral kinds, `access: read` or `write:<operation>`), `entities` (fields use only the allowed types: text, number, decimal, money, date, datetime, choice, boolean, attachment, link, external_ref, table), `workflow` (states, initial, final_states, transitions with roles and `require`), `roles` (permissions limited to create, read, update, update_own_draft, delete, approve, export), `rules` (ids R1, R2, ...), `reports`, `acceptance_tests` (ids AT-01, AT-02, ...). Names are snake_case.
   - `acceptance.md`: a Given/When/Then per acceptance test and a coverage line mapping each rule, transition, report and role to its tests.
   - `plan.md`: the build order and what is out of scope.
   - `design-review.md`: a decisions table (decision, reason, source) plus risks and open questions. Knowledge base and policy layers arrive in sub-project 2; until then cite spec/discovery sources manually in design-review.md.
3. Traceability is mandatory: every rule, every workflow transition and every role permission is covered by at least one acceptance test (`covers: [R1]`, `covers: [workflow]`, `covers: ["workflow:reject"]`, `covers: [permissions]`, `covers: [<report_name>]`).
4. Validate: `asb validate solutions/<name>`. It checks references, workflow reachability, traceability and the pack's capabilities. Fix every issue and re-run until it prints `OK: no issues`.
5. Present a summary to the human: entities, workflow, roles, rules, acceptance tests, risks, open questions.

## Outputs

`design/process-map.md`, `design/solution.yaml`, `design/acceptance.md`, `design/plan.md`, `design/design-review.md`.

## Gate

**Design approval** by a human, which records the model version and content hash. Ask them to run, in their terminal:

`asb approve <name> design --by "<their name>"`

If `solution.yaml` changes afterwards, the approved hash no longer matches and `asb build` refuses until the design is re-approved.

## Boundaries

- Never run `asb approve` or `asb use`; ask the human to.
- Do not design against external data discovery marked as a gap.
- Do not add features the requirements do not support; record them as open questions.
