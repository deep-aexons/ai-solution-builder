# AI Solution Builder

AI Solution Builder (ASB) turns a plain-language business request into a reviewed, tested module. A Python CLI (`asb`) records progress and enforces gates; a Claude plugin lets a developer or consultant drive the work in natural language. The core is platform-neutral: everything specific to a framework or a business system lives in **packs** (how to build) and **connectors** (how to reach a system).

## Why

When a client's ERP lacks a function, a traditional build is slow and hard to audit. ASB keeps people in charge of decisions and makes the evidence automatic: every rule and workflow transition is traced to an acceptance test, generated code is separated from AI-written code, and nothing moves forward without a recorded approval.

## The six stages

| # | Stage | Output in `solutions/<name>/` | Gate |
|---|---|---|---|
| 1 | Requirements | `requirements.md` | Human approves requirements |
| 2 | Discovery | `discovery.md` | Reviewed with the design |
| 3 | Design | `design/` (process map, `solution.yaml`, acceptance tests, plan, design review) | Human approves the design (version and hash recorded) |
| 4 | Build | `app/` | `asb check` passes |
| 5 | Verify | `verify-report.md`, `review.md` | All checks pass; at most 3 fix rounds; human accepts |
| 6 | Release | manual runbook only (see limits) | Client approval, then go-live approval |

`asb` refuses to start a stage whose prerequisites are missing (`asb gate <name> <stage>`).

## Quickstart

Prerequisites: Python 3.11 or later and [uv](https://docs.astral.sh/uv/). For a full verify you also want Node (`npm`, for the frontend build); Docker is needed only to run a generated app with Compose. Missing tools make the matching check report `skipped` with a reason.

```sh
uv sync
uv run asb --help
uv run asb new my-module --pack sidecar-django --connector erpnext
uv run asb status my-module
# write requirements.md, then, in your own terminal:
uv run asb approve my-module requirements --by "Your Name"
uv run asb discover my-module --kind outbound_shipment
uv run asb validate solutions/my-module          # once design/solution.yaml exists
uv run asb approve my-module design --by "Your Name"
uv run asb build my-module
uv run asb check my-module
uv run asb verify my-module
```

Commands: `new`, `status`, `approve`, `gate`, `validate`, `discover`, `build`, `check`, `verify`, `use`. Run `asb <command> --help` for options. Discovery needs `ASB_ERP_URL`, `ASB_ERP_API_KEY` and `ASB_ERP_API_SECRET` in the environment.

A worked example is in `solutions/gate-pass/`; the [user guide](docs/user-guide.md) walks through it.

## Install as a Claude plugin

The repository is a plugin marketplace (`aexons-asb`) with one plugin, `ai-solution-builder`. From Claude Code:

```
/plugin marketplace add <path-or-git-url-of-this-repo>
/plugin install ai-solution-builder@aexons-asb
```

You get six skills (one per stage, triggered by natural language such as "a client wants a gate pass module"), the `asb-reviewer` agent, the commands `/asb-new`, `/asb-status` and `/asb-approve`, and a PreToolUse hook that confines the AI to the active solution and blocks dangerous shell commands. The `asb` CLI must be runnable in the project (`uv run asb`).

The AI never records approvals: `asb approve` and `asb use` are for the human, and the hook blocks the AI from running them. The hook is a guardrail, not a sandbox.

## Current limits

- Sub-project 1 only: core, the `sidecar-django` pack, the `erpnext` connector, and the Gate Pass pilot.
- Sub-project 2 (knowledge base / RAG and the full policy engine) is not built. Until then the AI cites spec and discovery sources manually in `design-review.md`.
- Sub-project 3 (release automation: packaging, backup, deploy, rollback) is not built. Stage 6 is a manual checklist.
- The Gate Pass `discovery.md` was produced offline from a recorded ERPNext sample because the development VM cannot reach a live ERP; re-run `asb discover` against a real site before relying on it. Live-ERP and Docker Compose tests are skipped unless `ASB_ERP_URL` / `ASB_COMPOSE=1` are set, and the UI smoke check reports `skipped` when no browser is available.

## Documentation

- [User guide](docs/user-guide.md): Gate Pass end to end
- [Architecture](docs/architecture.md)
- [Writing a pack](docs/writing-a-pack.md)
- [Writing a connector](docs/writing-a-connector.md)
- [Changelog](CHANGELOG.md)
- Design spec and plan: `docs/superpowers/`
