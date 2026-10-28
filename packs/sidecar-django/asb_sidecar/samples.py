"""Sample specs for the generated test matrices.

Per entity: plain values, which fields must be made unique per record, required links to
build first, required attachments and child tables. The generated conftest turns a spec
into request bodies and ORM records at run time.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from asb.model import Entity, Field, Solution

_TEXT_CANDIDATES = ("sample", "SAMPLE", "SAMPLE 1", "A1", "a1", "123", "A-1", "x")
_SCALARS = (
    "text",
    "number",
    "decimal",
    "money",
    "date",
    "datetime",
    "choice",
    "boolean",
)


def _number(f: Field) -> float:
    lo, hi = f.min, f.max
    if (lo is None or lo <= 1) and (hi is None or hi >= 1):
        return 1
    return lo if lo is not None else hi  # type: ignore[return-value]


def _scalar(f: Field) -> Any:
    """A valid sample value, or None when none can be found."""
    t = f.type
    if t == "text":
        if f.pattern:
            return next((c for c in _TEXT_CANDIDATES if re.search(f.pattern, c)), None)
        return "sample"
    if t == "number":
        return int(_number(f))
    if t in ("decimal", "money"):
        places = 6 if t == "decimal" else 2
        return str(Decimal(str(_number(f))).quantize(Decimal(1).scaleb(-places)))
    if t == "date":
        return "2026-01-01"
    if t == "datetime":
        return "2026-01-01T00:00:00Z"
    if t == "boolean":
        return True
    if t == "choice":
        return f.options[0] if f.options else None
    return None


def _unique(f: Field, base: Any) -> dict[str, Any]:
    """How the run-time counter makes this field distinct for every record."""
    return {
        "type": f.type,
        "base": base,
        "lo": f.min,
        "hi": f.max,
        "pattern": f.pattern,
        "options": f.options,
        "places": 6 if f.type == "decimal" else 2,
    }


def _needed(solution: Solution, e: Entity) -> set[str]:
    return {
        r
        for w in solution.workflows
        if w.entity == e.name
        for t in w.transitions
        for r in t.require
    }


def _link_cycle(solution: Solution, start: str) -> list[str] | None:
    """A path of required links (all of them, depth first) from `start` that revisits an
    entity on the path, if any."""
    by_name = {e.name: e for e in solution.entities}

    def walk(path: list[str]) -> list[str] | None:
        entity = by_name.get(path[-1])
        if entity is None:
            return None
        for f in entity.fields:
            if f.type == "link" and f.required and f.to:
                for target in f.to:
                    if target in path:
                        return [*path, target]
                    found = walk([*path, target])
                    if found:
                        return found
        return None

    return walk([start])


def _spec(solution: Solution, e: Entity, depth: int = 0) -> dict[str, Any]:
    needed = _needed(solution, e)
    entities = {x.name: x for x in solution.entities}
    spec: dict[str, Any] = {
        "payload": {},
        "unique": {},
        "links": {},
        "files": [],
        "tables": {},
        "orm_fill": {},
        "parent": e.child_of,
        "api_problems": [],
        "orm_problems": [],
    }
    api, orm = spec["api_problems"], spec["orm_problems"]
    cycle = _link_cycle(solution, e.name)
    if cycle:
        orm.append("required link cycle " + " -> ".join(cycle))
    for f in e.fields:
        must = f.required or f.name in needed
        if f.type == "external_ref":
            if not f.read_only:
                spec["payload"][f"{f.name}_kind"] = (f.to or [""])[0]
                spec["payload"][f"{f.name}_id"] = "SAMPLE-1"
        elif f.type in _SCALARS:
            value = _scalar(f)
            if f.read_only:
                if must and value is not None:
                    spec["orm_fill"][f.name] = value
                continue
            if value is None:
                if must and f.type == "text":  # pattern: the ORM does not validate it
                    spec["orm_fill"][f.name] = "sample"
                    api.append(f"no sample matches the pattern of '{f.name}'")
                elif must:
                    orm.append(f"cannot sample {f.type} field '{f.name}'")
                continue
            spec["payload"][f.name] = value
            if f.unique:
                if f.type == "boolean":
                    orm.append(f"unique boolean field '{f.name}'")
                else:
                    spec["unique"][f.name] = _unique(f, value)
        elif f.type == "link":
            target = (f.to or [None])[0]
            if must and target in entities:
                spec["links"][f.name] = target
            elif must:
                orm.append(f"link '{f.name}' targets unknown entity")
        elif f.type == "attachment":
            if must:
                spec["files"].append(f.name)
        elif f.type == "table":
            child = entities.get(f.of or "")
            if child is None or depth >= 3:
                continue
            sub = _spec(solution, child, depth + 1)
            if must or not (sub["api_problems"] or sub["orm_problems"]):
                spec["tables"][f.name] = child.name
                api += [f"{f.name}: {p}" for p in sub["api_problems"]]
                orm += [f"{f.name}: {p}" for p in sub["orm_problems"]]
                if sub["files"] and must:
                    api.append(
                        f"{f.name}: rows with attachments cannot be posted as JSON"
                    )
    if spec["files"] and spec["tables"]:
        api.append("attachments and child rows cannot be posted in one request")
    return spec


def samples_context(solution: Solution) -> dict[str, Any]:
    """Entity name -> sample spec, for every entity (children and link targets included)."""
    out: dict[str, Any] = {}
    for e in solution.entities:
        spec = _spec(solution, e)
        patch = next(
            (
                f.name
                for f in e.fields
                if not f.read_only and f.type in _SCALARS and f.name in spec["payload"]
            ),
            None,
        )
        spec["patch"] = patch
        spec["api_reason"] = "; ".join(spec.pop("api_problems"))
        spec["orm_reason"] = "; ".join(spec.pop("orm_problems"))
        out[e.name] = spec
    return out
