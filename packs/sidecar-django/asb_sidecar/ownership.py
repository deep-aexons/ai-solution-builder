"""File ownership: AI-owned stubs are written once and never overwritten."""

from __future__ import annotations

import re
from pathlib import Path

from asb.model import Solution

from .errors import OrphanFileError

_RULE_FILE = re.compile(r"^r\d+\.py$")
_REPORT_FILE = re.compile(r"^[a-z][a-z0-9_]*\.py$")
_AT_FILE = re.compile(r"^test_at_\d{2,}\.py$")


def rule_module(rule_id: str) -> str:
    return rule_id.lower()


def at_module(test_id: str) -> str:
    return "test_at_" + test_id[3:]


def expected_stubs(solution: Solution) -> dict[str, str]:
    """Backend-relative stub path -> template, for every AI-owned file in the model."""
    stubs = {
        f"rules/{rule_module(r.id)}.py": "rules/rule.py.stub.j2" for r in solution.rules
    }
    stubs.update(
        {f"reports/{r.name}.py": "reports/report.py.stub.j2" for r in solution.reports}
    )
    stubs.update(
        {
            f"tests/{at_module(t.id)}.py": "tests/test_at.py.stub.j2"
            for t in solution.acceptance_tests
        }
    )
    return stubs


def find_orphans(solution: Solution, backend: Path) -> list[str]:
    """App-relative paths of AI-owned files that the model no longer asks for."""
    wanted = set(expected_stubs(solution))
    found: list[str] = []
    for folder, pattern in (
        ("rules", _RULE_FILE),
        ("reports", _REPORT_FILE),
        ("tests", _AT_FILE),
    ):
        base = backend / folder
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.py")):
            rel = f"{folder}/{path.name}"
            if (
                path.name != "__init__.py"
                and pattern.match(path.name)
                and rel not in wanted
            ):
                found.append(f"backend/{rel}")
    return found


def check_orphans(solution: Solution, backend: Path) -> None:
    orphans = find_orphans(solution, backend)
    if orphans:
        raise OrphanFileError(orphans)
