"""Template context for the workflow/permission/API layer (data the generated code reads)."""

from __future__ import annotations

import pprint
from typing import Any

from asb.model import Entity, Solution

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

    def lit(value: Any) -> str:
        return pprint.pformat(value, width=88, sort_dicts=False)

    return {
        "entities_lit": lit(entities),
        "workflows_lit": lit(workflows),
        "roles_lit": lit(roles),
        "role_names_lit": lit(sorted(role_names)),
        "reports_lit": lit([r.name for r in solution.reports]),
        "report_access_lit": lit(report_access),
        "model_entity_lit": lit({cls_name(e.name): e.name for e in solution.entities}),
    }
