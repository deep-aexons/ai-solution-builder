# Changelog

## 0.1.0

First release (sub-project 1: core, sidecar pack, ERPNext connector).

- `asb` CLI: `new`, `status`, `approve`, `gate`, `validate`, `discover`, `build`, `check`, `verify`, `use`.
- Solution model with validation: references, workflow reachability, traceability of rules, transitions and permissions to acceptance tests, pack capability check.
- Stage gates and approvals in `status.json` with an audit log; design approval records version and content hash; fix loops capped at 3 verify rounds.
- Pack `sidecar-django`: Django/DRF backend, React frontend, Docker Compose; generator-owned and AI-owned file split with a tamper-evident manifest; verification (tests, permission and workflow matrices, reports, static checks, frontend build, UI smoke).
- Connector `erpnext`: read access and approved draft creates; no delete, submit or cancel; credentials from the environment only.
- Static guardrail checks (`EVAL`, `RAW_SQL`, `SECRET`, `NO_PERMISSION`, `HEADER_TAMPERED`) and a PreToolUse hook confining the AI to the active solution.
- Basic ERP discovery (`discovery.md`).
- Claude plugin: six stage skills, `asb-reviewer` agent, `/asb-new`, `/asb-status`, `/asb-approve`, marketplace `aexons-asb`.
- Gate Pass pilot solution.
- Not included: knowledge base and policy engine (sub-project 2), release automation (sub-project 3).
