# AI Solution Builder — Design

- **Date:** 2026-10-28
- **Owner:** Deep (Aexons)
- **Status:** Draft for review
- **Repo:** `erp/ai-solution-builder` (independent of `erpnext-accelerator`)

## 1. Purpose

When a client asks for functionality their ERP (or other business system) does not have, Aexons uses this
AI ecosystem to turn a plain-language request into a reviewed, tested and deployable module — with less
effort and time than a traditional build, and with reliability backed by automated evidence.

### Success criteria

1. A consultant describes a workflow in ordinary language and gets back a requirements note, a process map,
   a solution design, acceptance criteria and an implementation plan for approval.
2. After approval, the builder generates a working module whose every acceptance test runs automatically.
3. Verification reports pass/fail for tests, permissions, workflows and reports, with no manual setup.
4. Nothing reaches a client environment without recorded approval, a backup and a rollback plan (sub-project 3).
5. The core has no knowledge of any specific ERP, framework or stack; those live in packs and connectors.
6. The AI works inside enforced boundaries (knowledge scopes + policy), not just instructions.

### Non-goals

- Changing the source code of any client ERP. Native ERP packs (e.g. Frappe, Odoo) are possible later but out of scope now.
- Fully autonomous delivery. People approve the design, the client release and go-live.
- Guaranteeing zero defects. The goal is traceable evidence: every rule and transition is covered by a passing test.

## 2. Decisions already made

| Topic | Decision |
|---|---|
| Form factor | Claude plugin (skills, sub-agents, commands, hooks) plus a Python CLI `asb` |
| Neutrality | Platform-neutral core; everything specific lives in **packs** (how to build) and **connectors** (how to reach a system) |
| First pack | **Universal sidecar**: standalone module app connecting to any ERP through a connector |
| Sidecar stack | Django 5 + Django REST Framework + React/TypeScript (Vite) + PostgreSQL, run with Docker Compose |
| First connector | ERPNext (demo site `erpnext.localhost`), targeting ERPNext v15/v16 stable APIs |
| Pilot solution | Gate Pass |
| v1 scope | Stages 1, 3, 4, 5 and basic stage 2; RAG/policy depth in sub-project 2; release in sub-project 3 |
| Isolation | Separate repo; no code shared with `erpnext-accelerator` |

## 3. The six-stage flow

| # | Stage | Output in `solutions/<name>/` | Gate |
|---|---|---|---|
| 1 | Business requirements | `requirements.md` — goals, users, current process, pain points, volumes, must/nice-to-have, open questions | Requirements confirmed by consultant |
| 2 | ERP discovery & analysis | `discovery.md` — data the solution needs, connector coverage, field/state semantics, conflicting customizations and rules, volumes, gaps | Reviewed within stage 3 |
| 3 | Solution design | `design/process-map.md` (Mermaid), `design/solution.yaml`, `design/acceptance.md`, `design/plan.md`, `design/design-review.md` | **Design approval** (records solution version + approver) |
| 4 | Build | `app/`, `build-log.md` | `asb check` passes (policy, conventions, traceability) |
| 5 | Verify | `verify-report.md` | All checks green + reviewer sign-off |
| 6 | Client approval & deployment | `release/` — change summary, UAT checklist, backup proof, staging result, deploy log, rollback steps | **Client approval** before staging; **go-live approval** before production |

`asb` records progress in `status.json` and refuses to run a stage whose prerequisites are incomplete or unapproved.
Build/verify fix loops are capped at **3 rounds**; after that the builder stops and reports to a person.

## 4. Repository structure

```
ai-solution-builder/
├── .claude-plugin/            plugin.json, marketplace.json
├── core/                      platform-neutral
│   ├── skills/                asb-requirements, asb-discovery, asb-design, asb-build, asb-verify, asb-release
│   ├── agents/asb-reviewer.md independent reviewer (fresh context; checks code against spec)
│   ├── commands/              /asb-new, /asb-status, /asb-approve (natural language also works)
│   ├── tool/                  `asb` CLI: model schema + validator, pack/connector loader, stage gates, checks
│   ├── knowledge/             RAG engine + `asb-knowledge` MCP server (sub-project 2)
│   └── policy/                policy engine + Claude Code hooks
├── packs/sidecar-django/      pack.yaml, generator/, verify/, deploy/, knowledge/, policy.yaml
├── connectors/
│   ├── interface.md           neutral connector contract
│   └── erpnext/               client, mapping.yaml, knowledge/, policy.yaml
├── solutions/<name>/          one folder per client solution (artefacts of all stages)
├── docs/                      README, user guide, architecture, writing a pack, writing a connector
└── tests/                     tests for core, packs and connectors
```

## 5. Solution model (`solution.yaml`)

The single source of truth between design and code. It describes the business, never a stack or ERP.

Top-level keys: `solution`, `version`, `description`, `external`, `entities`, `workflow`, `roles`, `rules`,
`reports`, `acceptance_tests`, `extensions`.

- **external** — data owned by the client system, by neutral kind (`outbound_shipment`, `inbound_receipt`,
  `customer`, `item`, …) with `access: read | write:<operation>`. Connectors map kinds to real names.
- **entities** — name, label, numbering pattern, fields, optional `child_of`.
- **Field types (fixed vocabulary):** text, number, decimal, money, date, datetime, choice, boolean,
  attachment, link (to own entity), external_ref (to external kind), table (child entity).
  Field options: required, default, pattern, min, max, options, unique, read_only.
- **workflow** — per entity: states, initial, transitions `{from, to, action, roles, require}`.
- **roles** — role → entity → permissions from: create, read, update, update_own_draft, delete, approve, export;
  plus report access.
- **rules** — `{id, text}` business rules, each implemented as one function and covered by tests.
- **reports** — entity, filters, columns, optional grouping/totals.
- **acceptance_tests** — `{id, covers: [rule ids | "workflow" | "permissions" | report names], text}`.
- **extensions** — `{<pack>: {...}}` explicit pack-specific hints; never required for correctness.

Validation (`asb validate`):

1. Schema and vocabulary are valid; names are unique snake_case.
2. Every reference resolves (links, external kinds, child entities, roles in transitions).
3. Workflow: initial state exists; every state is reachable; no dead-end state except declared final states
   (states with no outgoing transitions must be listed in `final_states`).
4. **Traceability:** every rule, every transition and every role permission is covered by at least one acceptance test.
5. The chosen pack declares support for every feature used (capabilities check).

The model is versioned; approvals reference the approved version and its content hash.

## 6. Packs

A pack turns a solution model into a running, testable, deployable app. Interface (`pack.yaml` + Python entry points):

| Function | Responsibility |
|---|---|
| `capabilities()` | Supported field types, workflow features, report features, versions |
| `generate(model, out_dir)` | Deterministic scaffolding: models, migrations, API, permissions, workflow, UI metadata, test skeletons |
| `verify(app_dir)` | Run tests, permission matrix, workflow checks, report checks, UI smoke; return a structured result |
| `deploy(app_dir, target)` | Package, back up, deploy, roll back (sub-project 3) |
| `knowledge/` | Documents indexed into scope `pack:<name>` |
| `policy.yaml` | Pack-specific rules (tightening only) |

### 6.1 Sidecar pack (`sidecar-django`)

Generated app layout:

```
app/
├── backend/   entities/ (models, migrations) · workflow/ (state machine + history) · api/ (DRF, permission classes)
│              rules/ (one function per rule) · reports/ · erp/ (connector client) · tests/
├── frontend/  React + TypeScript; metadata-driven list, form, workflow-action and report screens
├── docker-compose.yml   app + PostgreSQL (same file for test, staging, production)
└── README.md
```

- **Ownership split:** generator-owned files (models, migrations, API, permissions, UI metadata) carry a header
  and are regenerated freely; AI-owned files (`rules/`, report logic, test bodies) are never overwritten.
  Regeneration that would break AI-owned code fails loudly.
- Roles map to Django groups; object history records who changed what and when.
- Workflow is a small built-in state machine (no third-party FSM dependency); transitions check role and
  required fields and are recorded.
- Credentials and connector settings come from environment variables only.
- The UI renders from an API metadata endpoint, so little UI code is generated per entity; custom widgets via `extensions`.

## 7. Connectors

Neutral contract:

| Operation | Notes |
|---|---|
| `inspect()` | Kinds available, their fields and state semantics, version, installed modules |
| `get(kind, id)` / `list(kind, filters, fields, limit)` | Read live data; never copied into the sidecar except the reference |
| `create_draft(kind, data)` | Only for operations listed as `write:<operation>` in the approved model |
| delete / submit / cancel | Not part of the contract |

The ERPNext connector uses the REST API with an API key/secret from the environment, retries reads on transient
errors, and maps neutral kinds and states via `mapping.yaml` (e.g. `outbound_shipment → Delivery Note`,
`docstatus 1 → submitted`). It enforces approved write operations at runtime by checking the solution's approval record.

## 8. Knowledge base (RAG)

- **Storage:** one local SQLite file with FTS5 (keyword) and `sqlite-vec` (vector); local embeddings via
  `fastembed` (small ONNX model, CPU). No client data is sent to external embedding services.
- **Scopes:** `core` (Aexons playbook, lessons learned), `pack:<name>`, `connector:<name>`, `client:<client>`.
- **Retrieval:** hybrid search merged with reciprocal rank fusion, filtered by scope and target version; results
  include citations (source, section, version). Below a minimum score the tool returns "no reliable source", and
  the AI must ask or record an open question instead of guessing.
- **Isolation:** a solution may query only `core`, its pack, its connector and its own client scope. Enforced by the tool.
- **Ingestion:** `asb kb add <path|url> --scope …` chunks Markdown by heading and code by function/class; stores
  source, version and date; re-indexes changed files by content hash. `asb kb list|remove|stats`.
- **MCP server `asb-knowledge`:** `search_knowledge(query, scopes)`, `get_source(id)`, `client_snapshot(solution)`,
  `check_policy(action)`.
- Design decisions in `design-review.md` cite their sources.

## 9. Policy engine and boundaries

Layered files `core/policy.yaml` → `packs/<p>/policy.yaml` → `connectors/<c>/policy.yaml` → `solutions/<s>/policy.yaml`.
Later layers may only tighten. Loosening requires an entry in `solutions/<s>/exceptions.yaml` with reason, approver
and expiry; exceptions appear in the release pack.

| Rule type | Example |
|---|---|
| Paths | Writes only under `solutions/<s>/` (and `knowledge/` during ingestion) |
| Commands | Allow pytest, npm test, docker compose for the solution's test stack; deny destructive commands, `git push`, production hosts |
| Connector actions | Read allowed; writes only as approved; delete always denied |
| Code patterns | No raw SQL string building, no `eval`/`exec`, no hard-coded secrets, no API view without permission classes |
| Dependencies | Package and licence allowlist |
| Data | No real client data in tests/fixtures; personal data masked in client snapshots |
| Release | Production deploy needs go-live approval, a verified backup and a rollback plan |

Enforcement points: Claude Code `PreToolUse` hooks (file writes, shell commands); `asb` stage gates; connector
runtime checks; `asb check` (patterns, dependencies, secrets) runnable in CI. Every block, exception and approval
is appended to `solutions/<s>/audit.log`.

## 10. Verification (stage 5)

| Check | Pass condition |
|---|---|
| Acceptance tests | Each `AT-xx` maps to at least one automated test; all pass |
| Permission matrix | Every role × entity × action attempted via the API; outcome equals `roles:` |
| Workflow | Every allowed transition succeeds for permitted roles with required fields; every other role/transition is refused |
| Reports | Run on seeded data; filters and totals correct |
| Static checks | `asb check` clean; dependency audit clean; no secrets |
| UI smoke | Playwright: log in per role, open list/form, perform one transition, open each report |
| Review | `asb-reviewer` finds no unresolved high-severity issue against spec and code |

Result: `verify-report.md` with a pass/fail table, failures with evidence, and the fix round number.

## 11. Testing the builder itself

| Component | Tests |
|---|---|
| Model validator | Valid/invalid fixtures, including traceability and unreachable-state cases |
| Generator | Golden-file tests; generate-and-run test building a sample solution and running its suite |
| Verifiers | Deliberately broken sample apps that each checker must catch |
| Connector | Mock ERP server tests; optional live test against `erpnext.localhost` |
| Policy | Forbidden writes, commands, stage skips and connector writes are blocked |
| Knowledge (SP2) | Retrieval relevance fixtures; cross-client isolation test |

## 12. Prerequisites (developer machine)

Python 3.11+ with `uv`, Node 20+, Docker Desktop, git, Claude Code or Cowork. The ERPNext connector needs an API
key for a read-only (or limited) ERPNext user.

## 13. Sub-projects

| # | Sub-project | Delivers | Done when |
|---|---|---|---|
| 1 | Core + sidecar pack + ERPNext connector | Plugin skeleton, `asb` CLI, solution model + validator, stages 1/3/4/5 and basic stage 2 (connector `inspect`), reviewer agent, sidecar generator + verifier, ERPNext connector, basic path/command hooks, docs | Gate Pass goes from requirements to a verified running app reading `erpnext.localhost`, all acceptance tests green |
| 2 | Knowledge & boundaries | RAG, `asb-knowledge` MCP server, full layered policy, full discovery analysis, data masking | Stages cite sources; isolation and policy violations proven blocked by tests |
| 3 | Release manager | Stage 6: client review pack, approvals, backup, staging, production deploy, rollback | Gate Pass deployed to a staging stack and rolled back with full audit trail |
| 4 | Second connector (Odoo) | Neutrality proof | Gate Pass runs against Odoo without changing core or pack |

Each sub-project gets its own implementation plan. The first plan covers sub-project 1 only.

## 14. Pilot: Gate Pass (sub-project 1 acceptance)

- Entities: `gate_pass` (direction, external reference to outbound shipment or inbound receipt, vehicle number,
  driver, gate time, lines) and `gate_pass_line` (item, quantity).
- Workflow: draft → pending_security → approved/rejected → closed (final states: rejected, closed).
- Roles: store_user, security, manager.
- Rules: R1 reference must be submitted in the ERP; R2 pass quantities cannot exceed the reference quantities.
- Report: gate register (date range, direction, state).
- Reads Delivery Notes and Purchase Receipts from `erpnext.localhost` through the ERPNext connector; no ERP writes.

## 15. Risks

| Risk | Mitigation |
|---|---|
| Generated code drifts from the model after AI edits | Ownership split + regeneration check + traceability tests |
| AI guesses when knowledge is missing | "No reliable source" threshold; open questions recorded in design |
| Connector differences across ERP versions | Version-tagged mappings and knowledge; inspect() at discovery |
| Sidecar is a second app for the client to run | Single Docker Compose stack; README and runbook; native packs remain an option |
| Over-trust in automation | Human approvals at design, client release and go-live; reviewer agent is advisory, not an approver |
