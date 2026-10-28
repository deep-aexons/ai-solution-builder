"""The generated test suites (matrices, AT stubs) run inside the generated apps."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from asb_sidecar import generate

from asb.model import load_solution

HERE = Path(__file__).parent
FIXTURES = HERE.parent / "fixtures"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings", DEBUG="1", PYTHONDONTWRITEBYTECODE="1"
    )
    return env


def _pytest(backend: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *([] if "-v" in args else ["-q"]),
            "-p",
            "no:cacheprovider",
            *args,
        ],
        cwd=backend,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _counts(out: str) -> dict[str, int]:
    """Counts from pytest's final summary line, e.g. '2 failed, 38 passed, 1 error in 3s'."""
    last = [
        ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed|error)", ln)
    ][-1]
    found = {
        w: int(n)
        for n, w in re.findall(
            r"(\d+) (passed|failed|errors?|skipped|deselected)", last
        )
    }
    return {
        "passed": found.get("passed", 0),
        "failed": found.get("failed", 0),
        "errors": found.get("error", 0) + found.get("errors", 0),
        "skipped": found.get("skipped", 0),
    }


@pytest.mark.parametrize("fixture", ["gate_pass.yaml", "mini_docs.yaml"])
def test_matrices_pass_with_rules_stubbed(tmp_path, fixture):
    generate(load_solution(FIXTURES / fixture), tmp_path)
    proc = _pytest(tmp_path / "app/backend", "tests", "-m", "not at", "-rs")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "warnings summary" not in out, out
    counts = _counts(out)
    assert counts["failed"] == 0 and counts["errors"] == 0 and counts["passed"] > 0, out
    assert "sample-incomplete" not in out, out


def test_gate_pass_matrix_size_and_skips(tmp_path):
    generate(load_solution(FIXTURES / "gate_pass.yaml"), tmp_path)
    out = _pytest(tmp_path / "app/backend", "tests", "-m", "not at", "-rs", "-v")
    text = out.stdout
    # 3 roles x 1 entity x 7 permissions, 4 transitions x 3 roles (+4 wrong-state), 3 roles x 1 report
    assert text.count("test_permission_matrix.py::test_permission[") == 21
    assert text.count("test_workflow_matrix.py::test_transition_by_role[") == 12
    assert (
        text.count("test_workflow_matrix.py::test_transition_refused_in_other_states[")
        == 4
    )
    assert text.count("test_permission_matrix.py::test_report_access[") == 3
    # approve cases without an exercisable transition are skipped with a reason
    assert re.search(r"SKIPPED .*approve-not-exercisable: .*non-initial state", text)
    matrix = (tmp_path / "app/backend/tests/test_permission_matrix.py").read_text()
    assert "direction=outbound" not in matrix
    assert "'gate_register': ['date_range']" in matrix  # first declared filter


def test_mini_docs_exercises_every_permission(tmp_path):
    generate(load_solution(FIXTURES / "mini_docs.yaml"), tmp_path)
    proc = _pytest(tmp_path / "app/backend", "tests", "-m", "not at", "-v", "-rs")
    text = proc.stdout
    assert proc.returncode == 0, text
    for perm in (
        "create",
        "read",
        "update",
        "update_own_draft",
        "delete",
        "approve",
        "export",
    ):
        assert re.search(rf"editor-doc-{perm}\] PASSED", text), perm
    assert "author-doc-update_own_draft] PASSED" in text
    assert "editor-doc-approve] PASSED" in text  # editor may send_back from review


def test_at_stubs_fail_until_implemented(tmp_path):
    generate(load_solution(FIXTURES / "gate_pass.yaml"), tmp_path)
    backend = tmp_path / "app/backend"
    proc = _pytest(backend, "tests", "-m", "at")
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert _counts(out)["failed"] == 6
    for n in range(1, 7):
        assert f"AT-0{n} not implemented" in out
    assert "warnings summary" not in out, out
    full = _pytest(backend, "tests")
    assert full.returncode != 0 and _counts(full.stdout)["failed"] == 6
    assert _counts(full.stdout)["passed"] > 30


def test_rules_reports_and_export_in_generated_gate_pass_app(tmp_path):
    generate(load_solution(FIXTURES / "gate_pass.yaml"), tmp_path)
    backend = tmp_path / "app/backend"
    (backend / "rules/r1.py").write_text(
        "from rules import RuleViolation\n\n\n"
        "def check(obj, erp):\n"
        "    if obj.delivery_note_id:\n"
        '        doc = erp.get("outbound_shipment", obj.delivery_note_id)\n'
        '        if doc.get("_state") != "submitted":\n'
        '            raise RuleViolation(f"{obj.delivery_note_id} is not submitted")\n',
        encoding="utf-8",
    )
    (backend / "rules/r2.py").write_text(
        "from rules import RuleViolation\n\n\n"
        "def check(obj, erp):\n"
        '    if obj.driver == "Blocked":\n'
        '        raise RuleViolation("driver is blocked")\n',
        encoding="utf-8",
    )
    (backend / "reports/gate_register.py").write_text(
        "def run(filters):\n"
        "    from entities.models import GatePass\n\n"
        "    qs = GatePass.objects.all()\n"
        '    if filters.get("direction"):\n'
        '        qs = qs.filter(direction=filters["direction"])\n'
        '    return [{"direction": filters.get("direction"), "n": qs.count()}]\n',
        encoding="utf-8",
    )
    shutil.copy(HERE / "cases_rules_api.py", backend / "tests/test_rule_cases.py")
    proc = _pytest(backend, "tests/test_rule_cases.py")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "warnings summary" not in out, out
    # the generated matrices still pass with the real rules, thanks to rules_noop
    again = _pytest(backend, "tests", "-m", "not at")
    assert again.returncode == 0, again.stdout


def test_linked_entities_are_fully_exercised(tmp_path):
    """Required links, attachments, unique and patterned fields never cause skips."""
    generate(load_solution(FIXTURES / "linked_docs.yaml"), tmp_path)
    proc = _pytest(tmp_path / "app/backend", "tests", "-m", "not at", "-v", "-rs")
    text = proc.stdout
    assert proc.returncode == 0, text
    assert "sample-incomplete" not in text, text
    skips = [ln for ln in text.splitlines() if ln.startswith("SKIPPED")]
    assert skips, "approve cases without a transition are expected to skip"
    assert all("approve-not-exercisable:" in ln for ln in skips), skips
    for entity in ("customer", "purchase_order"):
        for perm in (
            "create",
            "read",
            "update",
            "update_own_draft",
            "delete",
            "export",
        ):
            assert re.search(rf"clerk-{entity}-{perm}\] PASSED", text), (entity, perm)
    assert "approver-purchase_order-approve] PASSED" in text
    assert "viewer-purchase_order-update] PASSED" in text
