"""Stage 5 verifier and the build/verify CLI; generated apps run in subprocesses."""

import importlib
import shutil
import textwrap
from pathlib import Path

import pytest
import yaml
from asb_sidecar import generate, verify
from typer.testing import CliRunner

from asb.cli import app
from asb.model import load_solution, parse_solution
from asb.plugins import CheckResult
from asb.status import approve, load_status, new_solution

verify_mod = importlib.import_module("asb_sidecar.verify")
REPO = Path(__file__).parents[2]
FIXTURES = REPO / "tests" / "fixtures"

TINY = {
    "solution": "ticketing",
    "version": 1,
    "description": "Tiny ticket desk used to prove the verifier.",
    "entities": [
        {
            "name": "ticket",
            "label": "Ticket",
            "fields": [
                {"name": "title", "type": "text", "required": True},
                {"name": "note", "type": "text"},
            ],
        }
    ],
    "workflow": {
        "entity": "ticket",
        "states": ["draft", "review", "done"],
        "initial": "draft",
        "final_states": ["done"],
        "transitions": [
            {"from": "draft", "to": "review", "action": "submit", "roles": ["worker"]},
            {
                "from": "review",
                "to": "done",
                "action": "finish",
                "roles": ["reviewer"],
            },
        ],
    },
    "roles": {
        "worker": {"ticket": ["create", "read", "update_own_draft", "delete"]},
        "reviewer": {"ticket": ["read", "approve"], "reports": ["ticket_list"]},
    },
    "rules": [{"id": "R1", "text": "A ticket title must not be 'forbidden'."}],
    "reports": [
        {
            "name": "ticket_list",
            "entity": "ticket",
            "filters": [],
            "columns": ["title", "state"],
        }
    ],
    "acceptance_tests": [
        {"id": "AT-01", "covers": ["R1"], "text": "A forbidden title is refused."},
        {
            "id": "AT-02",
            "covers": ["workflow"],
            "text": "Worker submits; reviewer finishes.",
        },
        {
            "id": "AT-03",
            "covers": ["ticket_list"],
            "text": "The reviewer can run the list.",
        },
        {"id": "AT-04", "covers": ["permissions"], "text": "A reviewer cannot create."},
    ],
}

RULE = """
from rules import RuleViolation


def check(obj, erp):
    if obj.title == "forbidden":
        raise RuleViolation("title is forbidden")
"""
REPORT = """
def run(filters):
    from entities.models import Ticket

    return [{"title": t.title, "state": t.state} for t in Ticket.objects.all()]
"""
AT_TESTS = {
    "AT-01": """
        client = api("worker")
        resp = client.post("/api/ticket/", {"title": "forbidden"}, format="json")
        assert resp.status_code == 400 and resp.json()["rule"] == "R1"
        assert client.post("/api/ticket/", {"title": "fine"}, format="json").status_code == 201
    """,
    "AT-02": """
        worker, reviewer = api("worker"), api("reviewer")
        pk = worker.post("/api/ticket/", {"title": "t"}, format="json").json()["id"]
        url = f"/api/ticket/{pk}/transition/"
        assert reviewer.post(url, {"action": "submit"}, format="json").status_code == 403
        assert worker.post(url, {"action": "submit"}, format="json").status_code == 200
        assert reviewer.post(url, {"action": "finish"}, format="json").json()["state"] == "done"
    """,
    "AT-03": """
        api("worker").post("/api/ticket/", {"title": "t"}, format="json")
        body = api("reviewer").get("/api/reports/ticket_list/").json()
        assert body["rows"] == [{"title": "t", "state": "draft"}]
    """,
    "AT-04": """
        assert api("reviewer").post("/api/ticket/", {"title": "t"}, format="json").status_code == 403
    """,
}


def implement(sol_dir: Path, ats=tuple(AT_TESTS)) -> None:
    """Write the rule, report and acceptance tests as the AI would."""
    backend = sol_dir / "app" / "backend"
    (backend / "rules" / "r1.py").write_text(RULE.lstrip(), encoding="utf-8")
    (backend / "reports" / "ticket_list.py").write_text(
        REPORT.lstrip(), encoding="utf-8"
    )
    for at in ats:
        n = at.split("-")[1]
        body = textwrap.indent(textwrap.dedent(AT_TESTS[at]).strip(), "    ")
        (backend / "tests" / f"test_at_{n}.py").write_text(
            f'import pytest\n\n\n@pytest.mark.at("{at}")\n'
            f"def test_at_{n}(api):\n{body}\n",
            encoding="utf-8",
        )


def by_name(result):
    return {c.name: c for c in result.checks}


@pytest.fixture
def no_frontend(monkeypatch):
    """Skip npm/browser in tests that do not need them."""
    monkeypatch.setattr(
        verify_mod,
        "check_frontend_build",
        lambda app: CheckResult("frontend_build", "skipped", "stubbed in test"),
    )


def test_broken_app_fails_mapping_tests_and_reports(tmp_path, no_frontend):
    sol = load_solution(FIXTURES / "gate_pass.yaml")
    generate(sol, tmp_path)
    (tmp_path / "app/backend/tests/test_at_01.py").write_text(
        'import pytest\n\n\n@pytest.mark.at("AT-01")\ndef test_at_01():\n    assert True\n'
    )
    (tmp_path / "app/backend/tests/test_at_03.py").unlink()  # not mapped at all
    got = by_name(verify(sol, tmp_path))
    assert list(got) == [
        "acceptance_mapping",
        "tests",
        "permission_matrix",
        "workflow_matrix",
        "reports",
        "static",
        "frontend_build",
        "ui_smoke",
    ]
    mapping = got["acceptance_mapping"]
    assert mapping.status == "fail"
    assert "AT-02" in mapping.details and "stub" in mapping.details
    assert "AT-03" in mapping.details and "AT-01" not in mapping.details
    assert got["tests"].status == "fail"
    assert "AT-02" in got["tests"].details or "test_at_02" in got["tests"].details
    assert got["reports"].status == "fail"  # report body not implemented
    assert got["permission_matrix"].status == "pass"
    assert got["workflow_matrix"].status == "pass"
    assert (
        got["ui_smoke"].status == "skipped"
        and "frontend_build" in got["ui_smoke"].details
    )


def test_tampered_generated_file_fails_static(tmp_path, no_frontend):
    sol = parse_solution(yaml.safe_dump(TINY).encode(), Path("t.yaml"))
    root = REPO_ROOT_FOR(tmp_path)
    sol_dir = new_solution(root, "ticketing", "sidecar-django", None)
    generate(sol, sol_dir, root=root)
    implement(sol_dir)
    with (sol_dir / "app/backend/api/views.py").open("a") as fh:
        fh.write("\n# edited\n")
    got = by_name(verify(sol, sol_dir, root=root))
    assert got["static"].status == "fail"
    assert "views.py" in got["static"].details


def REPO_ROOT_FOR(tmp_path: Path) -> Path:
    """A project root whose packs/ is the repository's (policy lookup) and anchors are tmp."""
    packs = tmp_path / "packs"
    if not packs.exists():
        packs.symlink_to(REPO / "packs")
    return tmp_path


@pytest.mark.slow
def test_clean_app_passes_everything(tmp_path):
    sol = parse_solution(yaml.safe_dump(TINY).encode(), Path("t.yaml"))
    root = REPO_ROOT_FOR(tmp_path)
    sol_dir = new_solution(root, "ticketing", "sidecar-django", None)
    generate(sol, sol_dir, root=root)
    implement(sol_dir)
    got = by_name(verify(sol, sol_dir, root=root))
    details = {k: (v.status, v.details) for k, v in got.items()}
    for name in ("acceptance_mapping", "tests", "permission_matrix", "workflow_matrix"):
        assert got[name].status == "pass", details
    assert got["reports"].status == "pass", details
    assert got["static"].status == "pass", details
    if shutil.which("npm"):
        assert got["frontend_build"].status in ("pass", "skipped"), details
    assert got["ui_smoke"].status in ("pass", "skipped"), details
    if got["frontend_build"].status == "pass":
        assert got["ui_smoke"].status == "pass", details
        assert (sol_dir / "app/frontend/dist/index.html").is_file()
        assert "worker/ticket: actions ['submit']" in got["ui_smoke"].details
    assert not any(c.status == "fail" for c in got.values()), details


@pytest.mark.slow
def test_ui_smoke_fails_on_a_report_that_breaks_with_data(tmp_path):
    sol = parse_solution(yaml.safe_dump(TINY).encode(), Path("t.yaml"))
    root = REPO_ROOT_FOR(tmp_path)
    sol_dir = new_solution(root, "ticketing", "sidecar-django", None)
    generate(sol, sol_dir, root=root)
    implement(sol_dir)
    (sol_dir / "app/backend/reports/ticket_list.py").write_text(
        "def run(filters):\n"
        "    from entities.models import Ticket\n\n"
        "    return [{'title': 1 / (t.pk - t.pk)} for t in Ticket.objects.all()]\n"
    )  # fine on an empty database, broken once a record exists
    got = by_name(verify(sol, sol_dir, root=root))
    if got["frontend_build"].status != "pass":
        pytest.skip("frontend build unavailable")
    assert got["reports"].status == "pass"
    assert got["ui_smoke"].status == "fail"
    assert "role reviewer" in got["ui_smoke"].details
    assert "ticket_list" in got["ui_smoke"].details


# CLI ----------------------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path, no_frontend):
    root = REPO_ROOT_FOR(tmp_path)
    sol_dir = new_solution(root, "ticketing", "sidecar-django", None)
    (sol_dir / "design" / "solution.yaml").write_text(
        yaml.safe_dump(TINY), encoding="utf-8"
    )
    return root, sol_dir


def cli(root, *args):
    return CliRunner().invoke(app, [*args, "--root", str(root)])


def approve_design(sol_dir):
    approve(sol_dir, "requirements", "t")
    approve(sol_dir, "design", "t")


def test_build_requires_design_approval(project):
    root, sol_dir = project
    result = cli(root, "build", "ticketing")
    assert result.exit_code == 1 and "design not approved" in result.output
    assert not (sol_dir / "app").exists()


def test_build_rejects_invalid_model_without_generating(project):
    root, sol_dir = project
    bad = {**TINY, "acceptance_tests": []}
    (sol_dir / "design" / "solution.yaml").write_text(yaml.safe_dump(bad))
    approve_design(sol_dir)
    result = cli(root, "build", "ticketing")
    assert result.exit_code == 1 and "TRACE_RULE" in result.output
    assert not (sol_dir / "app").exists()
    assert load_status(sol_dir).stages["build"] == "todo"


def test_verify_requires_build(project):
    root, sol_dir = project
    approve_design(sol_dir)
    result = cli(root, "verify", "ticketing")
    assert result.exit_code == 1 and "build not done" in result.output


def test_build_then_three_verifies_then_gate(project):
    root, sol_dir = project
    approve_design(sol_dir)
    built = cli(root, "build", "ticketing")
    assert built.exit_code == 0, built.output
    st = load_status(sol_dir)
    assert st.stages["build"] == "done" and st.verify_rounds == 0
    assert (root / ".asb" / "active").read_text().strip() == "ticketing"
    assert (root / ".asb" / "manifests" / "ticketing.sha256").is_file()

    first = cli(root, "verify", "ticketing")  # stubs untouched: fails
    assert first.exit_code == 1, first.output
    report = (sol_dir / "verify-report.md").read_text(encoding="utf-8")
    assert report.startswith("# Verify report — ticketing (round 1 of 3)")
    assert "| Check | Status | Details |" in report
    assert "| acceptance_mapping | fail |" in report
    assert "## Failures" in report and "## Skipped" in report
    assert "Result: FAIL" in report
    st = load_status(sol_dir)
    assert st.verify_rounds == 1 and st.stages["verify"] == "todo"

    implement(sol_dir)  # the fix
    second = cli(root, "verify", "ticketing")
    assert second.exit_code == 0, second.output
    report = (sol_dir / "verify-report.md").read_text(encoding="utf-8")
    assert "(round 2 of 3)" in report and "Result: PASS" in report
    assert "| frontend_build | skipped |" in report
    assert load_status(sol_dir).stages["verify"] == "done"

    assert cli(root, "verify", "ticketing").exit_code == 0  # round 3
    fourth = cli(root, "verify", "ticketing")
    assert fourth.exit_code == 1 and "fix-loop limit" in fourth.output
    assert load_status(sol_dir).verify_rounds == 3
    log = (sol_dir / "audit.log").read_text()
    assert "round=1 result=fail" in log and "round=2 result=pass" in log

    rebuilt = cli(root, "build", "ticketing")  # new build -> new verify cycle
    assert rebuilt.exit_code == 0, rebuilt.output
    st = load_status(sol_dir)
    assert st.verify_rounds == 0 and st.stages["verify"] == "todo"
    assert "kept" in rebuilt.output  # AI-owned files survive
