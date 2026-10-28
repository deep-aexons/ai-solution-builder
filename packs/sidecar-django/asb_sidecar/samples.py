"""Sample payloads for the generated test matrices (valid API bodies per entity)."""

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


def _scalar(f: Field) -> tuple[Any, str | None]:
    """(value, problem): value is None when the field cannot be sampled."""
    t = f.type
    if t == "text":
        if f.pattern:
            for cand in _TEXT_CANDIDATES:
                if re.search(f.pattern, cand):
                    return cand, None
            return None, f"no sample matches pattern of '{f.name}'"
        return "sample", None
    if t == "number":
        return int(_number(f)), None
    if t in ("decimal", "money"):
        places = 6 if t == "decimal" else 2
        return str(Decimal(str(_number(f))).quantize(Decimal(1).scaleb(-places))), None
    if t == "date":
        return "2026-01-01", None
    if t == "datetime":
        return "2026-01-01T00:00:00Z", None
    if t == "boolean":
        return True, None
    if t == "choice":
        if f.options:
            return f.options[0], None
        return None, f"choice '{f.name}' has no options"
    return None, f"cannot sample {t} field '{f.name}'"


def _entity(
    solution: Solution, e: Entity, depth: int = 0
) -> tuple[dict[str, Any], list[str], list[str]]:
    payload: dict[str, Any] = {}
    unique: list[str] = []
    problems: list[str] = []
    for f in e.fields:
        if f.read_only:
            if f.required and f.default is None and f.type != "table":
                problems.append(f"required read_only field '{f.name}'")
            continue
        if f.type == "external_ref":
            payload[f"{f.name}_kind"] = (f.to or [""])[0]
            payload[f"{f.name}_id"] = "SAMPLE-1"
        elif f.type == "table":
            child = next((c for c in solution.entities if c.name == f.of), None)
            if child is None or depth >= 3:
                continue
            row, _, child_problems = _entity(solution, child, depth + 1)
            if f.required or not child_problems:
                payload[f.name] = [row]
            if f.required or f.name in _required_by_transitions(solution, e):
                problems += [f"{f.name}: {p}" for p in child_problems]
            if any(c.unique for c in child.fields):
                problems.append(f"{f.name}: unique field on child rows")
        elif f.type in _SCALARS:
            value, problem = _scalar(f)
            if value is None:
                if f.required:
                    problems.append(problem or f"cannot sample '{f.name}'")
                continue
            payload[f.name] = value
            if f.unique:
                if f.type == "text" and f.pattern:
                    problems.append(f"unique '{f.name}' has a pattern")
                elif f.type in ("text", "number"):
                    unique.append(f.name)
                else:
                    problems.append(f"unique {f.type} field '{f.name}'")
        elif f.required:
            problems.append(f"required {f.type} field '{f.name}' cannot be sampled")
    return payload, unique, problems


def _required_by_transitions(solution: Solution, e: Entity) -> set[str]:
    return {
        r
        for w in solution.workflows
        if w.entity == e.name
        for t in w.transitions
        for r in t.require
    }


def samples_context(solution: Solution) -> dict[str, Any]:
    """Entity name -> sample description for every top-level entity."""
    out: dict[str, Any] = {}
    for e in solution.entities:
        if e.child_of:
            continue
        payload, unique, problems = _entity(solution, e)
        patch = next(
            (
                f.name
                for f in e.fields
                if not f.read_only and f.type in _SCALARS and f.name in payload
            ),
            None,
        )
        out[e.name] = {
            "payload": payload,
            "unique": unique,
            "patch": patch,
            "complete": not problems,
            "reason": "; ".join(problems),
        }
    return out
