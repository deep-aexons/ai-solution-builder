"""Gate Pass pilot: regenerate the committed solution from its design and verify it."""

import importlib.util
import shutil
from pathlib import Path

import pytest
from asb_sidecar import generate, verify

from asb.model import load_solution

REPO = Path(__file__).parents[2]
SOLUTION = REPO / "solutions" / "gate-pass"
BROWSER_STACK = bool(
    shutil.which("npm") and importlib.util.find_spec("playwright") is not None
)
# AI-owned files in the committed app (never produced by the generator).
AI_OWNED = [
    "rules/r1.py",
    "rules/r2.py",
    "rules/_ref.py",
    "reports/gate_register.py",
    "tests/_gp.py",
    "tests/test_erp_failures.py",
    *[f"tests/test_at_{n:02d}.py" for n in range(1, 7)],
]


def test_fixture_and_committed_design_are_identical():
    fixture = REPO / "tests" / "fixtures" / "gate_pass.yaml"
    assert fixture.read_bytes() == (SOLUTION / "design" / "solution.yaml").read_bytes()


@pytest.mark.slow
def test_gate_pass_regenerates_and_verifies(tmp_path):
    root = tmp_path / "project"
    sol_dir = root / "solutions" / "gate-pass"
    sol_dir.mkdir(parents=True)
    for name in ("packs", "connectors", "core"):
        (root / name).symlink_to(REPO / name)
    shutil.copytree(SOLUTION / "design", sol_dir / "design")
    for name in ("requirements.md", "discovery.md", "status.json"):
        shutil.copy2(SOLUTION / name, sol_dir / name)

    solution = load_solution(sol_dir / "design" / "solution.yaml")
    generate(solution, sol_dir, root=root)

    backend, committed = sol_dir / "app" / "backend", SOLUTION / "app" / "backend"
    for rel in AI_OWNED:
        target = backend / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(committed / rel, target)  # replaces the generated stub

    result = verify(solution, sol_dir, root=root)
    details = {c.name: (c.status, c.details) for c in result.checks}
    assert [c.name for c in result.checks if c.status == "fail"] == [], details
    assert len(result.checks) == 8, details
    assert details["acceptance_mapping"][0] == "pass", details
    if BROWSER_STACK:
        assert details["frontend_build"][0] == "pass", details
        assert details["ui_smoke"][0] == "pass", details
