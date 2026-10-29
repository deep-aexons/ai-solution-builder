---
name: asb-discovery
description: Use when requirements are approved and you need to find out what the client's ERP or business system actually holds, which data the solution can read, what is missing, or to run discovery or system analysis before design.
---

# Stage 2: System discovery

**Purpose:** inspect the client's system through the connector (read-only) and record what exists, what is missing and what needs a decision, in `solutions/<name>/discovery.md`.

**Inputs:** `requirements.md`, the solution's connector (from `status.json`), credentials in the environment.

## Steps

1. `asb status <name>` to confirm the connector is set.
2. Decide which external data the solution needs (for example outbound shipments, inbound receipts, customers, items). These are neutral *kinds* listed in the connector's `connector.yaml`.
3. Run discovery. Before a design exists, name the kinds:
   `asb discover <name> --kind <kind> [--kind <kind> ...]`
   Once `design/solution.yaml` exists, run `asb discover <name>` and it uses the model's `external` list (`--kind` is then ignored).
4. Read `solutions/<name>/discovery.md`: connection, external data table (kind, system document, fields available, sample records, status), write access requested, **Gaps**, notes for design.
5. Record gaps and open questions for the consultant: every kind that is not `ok`, missing fields, customisations or rules that may conflict with the requirements. Add them to the Open questions in `requirements.md` or tell the consultant directly; design only against data marked `ok`.

## If discovery fails

`asb discover` exits 1, writes the failure into `discovery.md` and leaves the stage not done. The connector reads credentials only from the environment. Tell the human to set, in their own shell:

- `ASB_ERP_URL` (base URL of the system)
- `ASB_ERP_API_KEY`
- `ASB_ERP_API_SECRET`

then re-run. Never ask for the secret values in chat, never write them to a file, and never put them in a command line. Discovery never writes to the client's system. If the system is unreachable, say so plainly; do not substitute invented data.

## Outputs

`solutions/<name>/discovery.md`; stage 2 marked done when the run connects.

## Gate

None of its own: discovery is reviewed as part of design approval. The design must not rely on gaps that are unresolved.

## Boundaries

- Never run `asb approve` or `asb use`; ask the human to.
- Read-only: no connector write operations.
- Knowledge base and policy layers arrive in sub-project 2; until then cite spec/discovery sources manually in design-review.md.
