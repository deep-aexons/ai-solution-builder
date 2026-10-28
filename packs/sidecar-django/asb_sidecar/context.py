"""Template context for the workflow/permission/API layer (data the generated code reads)."""

from __future__ import annotations

import pprint
from typing import Any

from asb.model import PERMISSIONS, Entity, Solution

# Entity names that would collide with fixed API routes.
RESERVED_ROUTES = {"meta", "auth", "reports"}


def cls_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _attrs(name: str, type_: str) -> list[str]:
    if type_ == "table":
        return []
    if type_ == "external_ref":
        return [f"{name}_kind", f"{name}_id"]
    return [name]


def _entity_def(e: Entity) -> dict[str, Any]:
    return {
        "label": e.label,
        "model": cls_name(e.name),
        "numbering": e.numbering,
        "child_of": e.child_of,
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "required": f.required,
                "options": f.options,
                "to": f.to,
                "of": f.of,
                "read_only": f.read_only,
            }
            for f in e.fields
        ],
        "field_attrs": {f.name: _attrs(f.name, f.type) for f in e.fields},
        "attrs": [a for f in e.fields for a in _attrs(f.name, f.type)],
        "read_only_attrs": [
            a for f in e.fields if f.read_only for a in _attrs(f.name, f.type)
        ],
        "read_only_tables": [
            f.name for f in e.fields if f.type == "table" and f.read_only
        ],
        "tables": [
            {"name": f.name, "of": f.of} for f in e.fields if f.type == "table" and f.of
        ],
    }


def lit(value: Any) -> str:
    return pprint.pformat(value, width=88, sort_dicts=False)


def definitions_context(solution: Solution) -> dict[str, str]:
    """Python-literal source for workflow/definitions.py (all values are plain data)."""
    for e in solution.entities:
        if e.name in RESERVED_ROUTES:
            raise ValueError(f"entity '{e.name}': name is reserved")
    entities = {e.name: _entity_def(e) for e in solution.entities}
    workflows = {
        w.entity: {
            "states": list(w.states),
            "initial": w.initial,
            "final_states": list(w.final_states),
            "transitions": [
                {
                    "from": t.from_,
                    "to": t.to,
                    "action": t.action,
                    "roles": list(t.roles),
                    "require": list(t.require),
                }
                for t in w.transitions
            ],
        }
        for w in solution.workflows
    }
    roles = {
        role: {k: list(v) for k, v in targets.items() if k != "reports"}
        for role, targets in solution.roles.items()
    }
    report_access = {
        role: list(targets.get("reports", []))
        for role, targets in solution.roles.items()
    }
    role_names = set(roles)
    for w in solution.workflows:
        for t in w.transitions:
            role_names.update(t.roles)

    return {
        "entities_lit": lit(entities),
        "workflows_lit": lit(workflows),
        "roles_lit": lit(roles),
        "role_names_lit": lit(sorted(role_names)),
        "reports_lit": lit([r.name for r in solution.reports]),
        "report_access_lit": lit(report_access),
        "model_entity_lit": lit({cls_name(e.name): e.name for e in solution.entities}),
    }


def layer_context(solution: Solution, connector_entry: str | None) -> dict[str, Any]:
    """Data for rules, reports, the ERP adapter and the generated test suites."""
    from .samples import samples_context

    base = definitions_context(solution)
    top = [e for e in solution.entities if not e.child_of]
    top_names = {e.name for e in top}
    workflows = [w for w in solution.workflows if w.entity in top_names]
    transitions = [
        {
            "entity": w.entity,
            "from": t.from_,
            "to": t.to,
            "action": t.action,
            "roles": list(t.roles),
            "require": list(t.require),
        }
        for w in workflows
        for t in w.transitions
    ]
    report_specs = {
        r.name: {
            "entity": r.entity,
            "filters": list(r.filters),
            "columns": list(r.columns),
        }
        for r in solution.reports
    }
    role_names = sorted(
        {
            *solution.roles,
            *(r for w in solution.workflows for t in w.transitions for r in t.roles),
        }
    )
    writes = sorted(
        f"write:{x.kind}" for x in solution.external if x.access.startswith("write:")
    )
    connector = (
        {"entry": connector_entry, "allowed_writes_lit": lit(writes)}
        if connector_entry
        else None
    )
    return {
        **base,
        "connector": connector,
        "allowed_writes_lit": lit(writes),
        "rules_lit": lit([(r.id, r.id.lower()) for r in solution.rules]),
        "report_specs_lit": lit(report_specs),
        "samples_lit": lit(samples_context(solution)),
        "top_entities_lit": lit([e.name for e in top]),
        "transitions_lit": lit(transitions),
        "states_lit": lit({w.entity: list(w.states) for w in workflows}),
        "has_transitions": bool(transitions),
        "has_other_state": any(
            any(
                not any(x.action == t.action and x.from_ == st for x in w.transitions)
                for st in w.states
            )
            for w in workflows
            for t in w.transitions
        ),
        "other_state_lit": lit(
            [
                any(
                    not any(
                        x.action == t.action and x.from_ == st for x in w.transitions
                    )
                    for st in w.states
                )
                for w in workflows
                for t in w.transitions
            ]
        ),
        "initial_lit": lit({w.entity: w.initial for w in workflows}),
        "field_attrs_lit": lit({e.name: _entity_def(e)["field_attrs"] for e in top}),
        "permissions_lit": lit(list(PERMISSIONS)),
        "report_filters_lit": lit(
            {n: (r["filters"][:1]) for n, r in report_specs.items()}
        ),
        "report_cases": lit([(r, rep) for r in role_names for rep in report_specs])
        if report_specs
        else "",
    }
