"""Semantic validation of a solution model: references, workflows, traceability."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from asb.model import Solution


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.path}: {self.message}"


def _dupes(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n in seen and n not in out:
            out.append(n)
        seen.add(n)
    return out


def _check_duplicates(sol: Solution, out: list[Issue]) -> None:
    def report(kind: str, names: list[str], path: str) -> None:
        for n in _dupes(names):
            out.append(Issue("DUPLICATE_NAME", path, f"duplicate {kind} '{n}'"))

    report("entity", [e.name for e in sol.entities], "entities")
    for i, e in enumerate(sol.entities):
        report("field", [f.name for f in e.fields], f"entities.{i}.fields")
    report("rule id", [r.id for r in sol.rules], "rules")
    report(
        "acceptance test id", [a.id for a in sol.acceptance_tests], "acceptance_tests"
    )
    report("report", [r.name for r in sol.reports], "reports")
    for i, w in enumerate(sol.workflows):
        report("state", w.states, f"workflow.{i}.states")


def _check_refs(sol: Solution, out: list[Issue]) -> None:
    entities = {e.name: e for e in sol.entities}
    externals = {x.name for x in sol.external}

    def unknown(path: str, what: str, name: str) -> None:
        out.append(Issue("REF_UNKNOWN", path, f"unknown {what} '{name}'"))

    for i, e in enumerate(sol.entities):
        if e.child_of is not None and e.child_of not in entities:
            unknown(f"entities.{i}.child_of", "entity", e.child_of)
        for j, f in enumerate(e.fields):
            p = f"entities.{i}.fields.{j}"
            if f.type == "external_ref":
                if not f.to:
                    out.append(
                        Issue("REF_UNKNOWN", f"{p}.to", "external_ref needs 'to'")
                    )
                for t in f.to or []:
                    if t not in externals:
                        unknown(f"{p}.to", "external", t)
            elif f.type == "link":
                if not f.to:
                    out.append(Issue("REF_UNKNOWN", f"{p}.to", "link needs 'to'"))
                for t in f.to or []:
                    if t not in entities:
                        unknown(f"{p}.to", "entity", t)
            elif f.type == "table":
                if f.of is None:
                    out.append(Issue("REF_UNKNOWN", f"{p}.of", "table needs 'of'"))
                elif f.of not in entities:
                    unknown(f"{p}.of", "entity", f.of)
                elif entities[f.of].child_of != e.name:
                    out.append(
                        Issue(
                            "REF_UNKNOWN",
                            f"{p}.of",
                            f"entity '{f.of}' is not a child_of '{e.name}'",
                        )
                    )

    for i, w in enumerate(sol.workflows):
        p = f"workflow.{i}"
        ent = entities.get(w.entity)
        if ent is None:
            unknown(f"{p}.entity", "entity", w.entity)
        states = set(w.states)
        for s in w.final_states:
            if s not in states:
                unknown(f"{p}.final_states", "state", s)
        for k, t in enumerate(w.transitions):
            tp = f"{p}.transitions.{k}"
            for end, val in (("from", t.from_), ("to", t.to)):
                if val not in states:
                    unknown(f"{tp}.{end}", "state", val)
            for r in t.roles:
                if r not in sol.roles:
                    unknown(f"{tp}.roles", "role", r)
            if ent is not None:
                fields = {f.name for f in ent.fields}
                for req in t.require:
                    if req not in fields:
                        unknown(f"{tp}.require", "field", req)

    report_names = {r.name for r in sol.reports}
    for i, r in enumerate(sol.reports):
        if r.entity not in entities:
            unknown(f"reports.{i}.entity", "entity", r.entity)

    for role, targets in sol.roles.items():
        for target, perms in targets.items():
            if target == "reports":
                for rn in perms:
                    if rn not in report_names:
                        unknown(f"roles.{role}.reports", "report", rn)
            elif target not in entities:
                unknown(f"roles.{role}.{target}", "entity", target)


def _check_workflows(sol: Solution, out: list[Issue]) -> None:
    for i, w in enumerate(sol.workflows):
        p = f"workflow.{i}"
        if w.initial not in w.states:
            out.append(
                Issue(
                    "WF_NO_INITIAL",
                    f"{p}.initial",
                    f"initial state '{w.initial}' not in states",
                )
            )
            continue
        graph: dict[str, list[str]] = {s: [] for s in w.states}
        for t in w.transitions:
            if t.from_ in graph:
                graph[t.from_].append(t.to)
        seen = {w.initial}
        queue = deque([w.initial])
        while queue:
            for nxt in graph.get(queue.popleft(), []):
                if nxt not in seen and nxt in graph:
                    seen.add(nxt)
                    queue.append(nxt)
        for s in w.states:
            if s not in seen:
                out.append(
                    Issue(
                        "WF_UNREACHABLE",
                        f"{p}.states",
                        f"state '{s}' is not reachable from '{w.initial}'",
                    )
                )
            if not graph[s] and s not in w.final_states:
                out.append(
                    Issue(
                        "WF_DEAD_END",
                        f"{p}.states",
                        f"state '{s}' has no outgoing transition and is not final",
                    )
                )


def _check_traceability(sol: Solution, out: list[Issue]) -> None:
    rule_ids = {r.id for r in sol.rules}
    report_names = {r.name for r in sol.reports}
    actions = {t.action for w in sol.workflows for t in w.transitions}
    valid_tokens = rule_ids | report_names | {"workflow", "permissions"}
    valid_tokens |= {f"workflow:{a}" for a in actions}
    valid_tokens |= {f"permissions:{r}" for r in sol.roles}

    covered: set[str] = set()
    for i, at in enumerate(sol.acceptance_tests):
        for token in at.covers:
            if token in valid_tokens:
                covered.add(token)
            else:
                out.append(
                    Issue(
                        "REF_UNKNOWN",
                        f"acceptance_tests.{i}.covers",
                        f"unknown cover target '{token}'",
                    )
                )

    for i, r in enumerate(sol.rules):
        if r.id not in covered:
            out.append(
                Issue("TRACE_RULE", f"rules.{i}", f"rule {r.id} has no acceptance test")
            )
    for i, w in enumerate(sol.workflows):
        for k, t in enumerate(w.transitions):
            if not ({"workflow", f"workflow:{t.action}"} & covered):
                out.append(
                    Issue(
                        "TRACE_TRANSITION",
                        f"workflow.{i}.transitions.{k}",
                        f"transition ({w.entity}, {t.action}) has no acceptance test",
                    )
                )
    for role in sol.roles:
        if not ({"permissions", f"permissions:{role}"} & covered):
            out.append(
                Issue(
                    "TRACE_PERMISSION",
                    f"roles.{role}",
                    f"permissions of role '{role}' have no acceptance test",
                )
            )
    for i, r in enumerate(sol.reports):
        if r.name not in covered:
            out.append(
                Issue(
                    "TRACE_RULE",
                    f"reports.{i}",
                    f"report '{r.name}' has no acceptance test",
                )
            )


def _check_capabilities(sol: Solution, caps: dict[str, Any], out: list[Issue]) -> None:
    allowed = caps.get("field_types")
    if allowed is None:
        return
    for i, e in enumerate(sol.entities):
        for j, f in enumerate(e.fields):
            if f.type not in allowed:
                out.append(
                    Issue(
                        "CAPABILITY",
                        f"entities.{i}.fields.{j}.type",
                        f"field type '{f.type}' is not supported by the target pack",
                    )
                )


def validate(
    solution: Solution, capabilities: dict[str, Any] | None = None
) -> list[Issue]:
    out: list[Issue] = []
    _check_duplicates(solution, out)
    _check_refs(solution, out)
    _check_workflows(solution, out)
    _check_traceability(solution, out)
    if capabilities:
        _check_capabilities(solution, capabilities, out)
    return out
