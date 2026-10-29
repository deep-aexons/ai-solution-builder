---
name: asb-requirements
description: Use when a client or consultant describes a new workflow, module or gap they want built, or asks to start a new solution, capture business requirements, or write a requirements note. Stage 1 of the AI Solution Builder pipeline.
---

# Stage 1: Business requirements

**Purpose:** turn a plain-language request into `solutions/<name>/requirements.md` that a consultant confirms. No design or code yet.

**Inputs:** the client's description, the consultant's answers, any documents they share.

## Steps

1. If no solution folder exists, create one. Names are lowercase with hyphens. Ask which pack (see `packs/`) and which connector (see `connectors/`), then run:
   `asb new <name> --pack <pack> --connector <connector>`
   This also makes the solution active, so the PreToolUse hook confines your writes to `solutions/<name>/`.
2. Check where things stand: `asb status <name>`.
3. Interview the consultant **one question at a time**, in plain language. Cover, in this order: goal; who uses it and what each role does; the current process and its pain points; volumes (records per day/year, concurrent users); must-have; nice-to-have; what is unknown. Do not move on while an answer is vague; offer a concrete assumption and ask them to confirm.
4. Write `solutions/<name>/requirements.md` with these sections (see `solutions/gate-pass/requirements.md` for a worked example): **Goal**, **In the client's words**, **Users and roles** (table), **Current process and pain points**, **Volumes**, **Must have** (numbered), **Nice to have**, **Open questions** (numbered; mark assumptions).
5. Read it back to the consultant, fix what they correct, then ask them to approve (below).

## Outputs

`solutions/<name>/requirements.md`.

## Gate

Requirements are confirmed by a human. Ask the consultant to run, in their own terminal:

`asb approve <name> requirements --by "<their name>"`

Stage 3 (design) will not start without it (`asb gate <name> design` refuses).

## Boundaries

- Never run `asb approve` or `asb use`; ask the human to. The hook blocks them anyway.
- Never invent requirements: anything not said goes under Open questions.
- Stay neutral: describe the business, not the technology. The pack and connector are chosen by name only.
- Knowledge base and policy layers arrive in sub-project 2; until then cite spec/discovery sources manually in design-review.md.
