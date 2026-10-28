"""`asb check` over a freshly generated app: clean, and tampering is caught."""

from pathlib import Path

import pytest
from asb_sidecar import generate

from asb.checks import load_policy, run_checks
from asb.model import load_solution

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "gate_pass.yaml"


@pytest.fixture(scope="module")
def policy():
    return load_policy(ROOT, "sidecar-django")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    sol_dir = tmp_path_factory.mktemp("sol")
    generate(load_solution(FIXTURE), sol_dir)
    return sol_dir / "app"


def test_generated_app_is_clean(built, policy):
    assert run_checks(built, policy) == []


def test_edit_to_generated_file_is_detected(built, policy):
    target = built / "backend" / "api" / "errors.py"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\nx = 1\n")
        issues = run_checks(built, policy)
    finally:
        target.write_bytes(original)
    assert [(i.code, i.path) for i in issues] == [
        ("HEADER_TAMPERED", "backend/api/errors.py")
    ]


def test_ai_code_in_generated_app_is_scanned(built, policy):
    extra = built / "backend" / "rules" / "r99.py"
    extra.write_text(
        "def f(cur, x):\n    cur.execute(f'select {x}')\n", encoding="utf-8"
    )
    try:
        issues = run_checks(built, policy)
    finally:
        extra.unlink()
    assert [(i.code, i.path) for i in issues] == [("RAW_SQL", "backend/rules/r99.py")]
