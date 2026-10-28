import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from asb.cli import app
from asb.status import (
    STAGES,
    GateError,
    approve,
    increment_verify_rounds,
    load_status,
    mark_done,
    new_solution,
    require,
    save_status,
)

FIX = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sol(tmp_path):
    return new_solution(tmp_path, "gate-pass", "sidecar-django", "erpnext")


def put_model(d: Path) -> Path:
    target = d / "design" / "solution.yaml"
    shutil.copy(FIX / "gate_pass.yaml", target)
    return target


def test_new_creates_layout(sol, tmp_path):
    assert sol == tmp_path / "solutions" / "gate-pass"
    for name in ("requirements.md", "discovery.md", "status.json", "audit.log"):
        assert (sol / name).is_file()
    assert (sol / "design").is_dir()
    assert (sol / "design" / ".gitkeep").is_file()
    st = load_status(sol)
    assert st.solution == "gate-pass"
    assert st.pack == "sidecar-django"
    assert st.connector == "erpnext"
    assert list(st.stages) == STAGES
    assert set(st.stages.values()) == {"todo"}
    assert st.verify_rounds == 0


def test_new_rejects_bad_name_and_existing(sol, tmp_path):
    with pytest.raises(ValueError):
        new_solution(tmp_path, "Bad_Name", "p", None)
    with pytest.raises(FileExistsError):
        new_solution(tmp_path, "gate-pass", "p", None)


def test_design_requires_requirements_approval(sol):
    with pytest.raises(GateError):
        require(sol, "design")
    approve(sol, "requirements", "Deep")
    require(sol, "design")
    require(sol, "requirements")
    require(sol, "discovery")


def test_build_requires_design_approval(sol):
    with pytest.raises(GateError, match="design not approved"):
        require(sol, "build")
    put_model(sol)
    approve(sol, "design", "Deep")
    require(sol, "build")
    a = load_status(sol).approvals[-1]
    assert a.kind == "design" and a.model_hash and a.model_version is not None


def test_approve_design_needs_valid_model(sol):
    with pytest.raises(GateError):
        approve(sol, "design", "Deep")
    (sol / "design" / "solution.yaml").write_text("nope: 1\n")
    with pytest.raises(GateError):
        approve(sol, "design", "Deep")


def test_build_refused_after_model_change(sol):
    target = put_model(sol)
    approve(sol, "design", "Deep")
    target.write_text(target.read_text() + "\n# edited\n")
    with pytest.raises(GateError, match="approved hash differs"):
        require(sol, "build")


def test_latest_design_approval_counts(sol):
    target = put_model(sol)
    approve(sol, "design", "Deep")
    target.write_text(target.read_text() + "\n# edited\n")
    approve(sol, "design", "Deep")
    require(sol, "build")


def test_verify_and_release_gates(sol):
    with pytest.raises(GateError):
        require(sol, "verify")
    mark_done(sol, "build")
    require(sol, "verify")
    with pytest.raises(GateError):
        require(sol, "release")
    mark_done(sol, "verify")
    with pytest.raises(GateError):
        require(sol, "release")
    approve(sol, "client", "Client Co")
    require(sol, "release")


def test_fix_loop_limit(sol):
    mark_done(sol, "build")
    st = load_status(sol)
    st.verify_rounds = 3
    save_status(sol, st)
    with pytest.raises(GateError, match="fix-loop limit reached"):
        require(sol, "verify")


def test_increment_verify_rounds(sol):
    assert increment_verify_rounds(sol) == 1
    assert increment_verify_rounds(sol) == 2
    assert load_status(sol).verify_rounds == 2


def test_audit_log_written(sol):
    approve(sol, "requirements", "Deep")
    with pytest.raises(GateError):
        require(sol, "build")
    mark_done(sol, "requirements")
    lines = (sol / "audit.log").read_text().splitlines()
    assert len(lines) >= 3
    for line in lines:
        ts, event, detail = line.split("\t")
        assert ts.endswith("Z") or "+00:00" in ts
        assert event and detail
    events = [line.split("\t")[1] for line in lines]
    assert "approve" in events and "gate_failed" in events and "mark_done" in events


def test_cli_flow(tmp_path):
    r = CliRunner()
    root = ["--root", str(tmp_path)]
    res = r.invoke(
        app,
        [
            "new",
            "gate-pass",
            "--pack",
            "sidecar-django",
            "--connector",
            "erpnext",
            *root,
        ],
    )
    assert res.exit_code == 0, res.output
    d = tmp_path / "solutions" / "gate-pass"
    res = r.invoke(app, ["gate", "gate-pass", "build", *root])
    assert res.exit_code == 1
    assert "design not approved" in res.output
    put_model(d)
    res = r.invoke(app, ["approve", "gate-pass", "design", "--by", "Deep", *root])
    assert res.exit_code == 0, res.output
    res = r.invoke(app, ["gate", "gate-pass", "build", *root])
    assert res.exit_code == 0 and "OK" in res.output
    res = r.invoke(app, ["status", "gate-pass", *root])
    assert res.exit_code == 0
    assert "design" in res.output and "Deep" in res.output
    assert "verify_rounds" in res.output
    assert r.invoke(app, ["status", "missing", *root]).exit_code == 1
    assert r.invoke(app, ["new", "Bad", "--pack", "p", *root]).exit_code == 1


def test_corrupt_status_raises_gate_error(sol):
    (sol / "status.json").write_text("{not json")
    with pytest.raises(GateError, match="status.json is corrupt"):
        load_status(sol)
    (sol / "status.json").write_text('{"solution": 1}')
    with pytest.raises(GateError, match="status.json is corrupt"):
        require(sol, "design")


def test_save_leaves_no_temp_files(sol):
    save_status(sol, load_status(sol))
    assert sorted(p.name for p in sol.iterdir()) == [
        "audit.log",
        "design",
        "discovery.md",
        "requirements.md",
        "status.json",
    ]


def test_approve_unknown_kind(sol):
    with pytest.raises(ValueError, match="requirements"):
        approve(sol, "bogus", "x")


def test_cli_rejects_bad_names_and_corrupt_status(tmp_path):
    r = CliRunner()
    root = ["--root", str(tmp_path)]
    res = r.invoke(app, ["status", "../x", *root])
    assert res.exit_code == 1 and "invalid solution name" in res.output
    d = new_solution(tmp_path, "ok", "p", None)
    (d / "status.json").write_text("garbage")
    res = r.invoke(app, ["status", "ok", *root])
    assert res.exit_code == 1 and "corrupt" in res.output
    assert "Traceback" not in res.output
    res = r.invoke(app, ["approve", "ok", "bogus", "--by", "x", *root])
    assert res.exit_code == 1


def test_missing_status_is_not_corrupt(sol):
    (sol / "status.json").unlink()
    with pytest.raises(GateError, match="status.json not found"):
        load_status(sol)
