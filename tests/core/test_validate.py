from pathlib import Path

import yaml
from typer.testing import CliRunner

from asb.cli import app
from asb.model import Solution, load_solution
from asb.validate import Issue, validate

FIX = Path(__file__).parent.parent / "fixtures"


def _sol(mutate=None) -> Solution:
    data = yaml.safe_load((FIX / "gate_pass.yaml").read_text())
    if mutate:
        mutate(data)
    return Solution.model_validate(data)


def _codes(issues):
    return sorted({i.code for i in issues})


def test_gate_pass_is_clean():
    assert validate(load_solution(FIX / "gate_pass.yaml")) == []


def test_issue_fields():
    i = Issue("X", "a.b", "msg")
    assert (i.code, i.path, i.message) == ("X", "a.b", "msg")


def test_external_ref_unknown_external():
    def m(d):
        d["entities"][0]["fields"][1]["to"] = ["nope"]

    issues = validate(_sol(m))
    assert _codes(issues) == ["REF_UNKNOWN"]
    assert issues[0].path == "entities.0.fields.1.to"
    assert "nope" in issues[0].message


def test_table_of_must_be_child():
    def m(d):
        d["entities"][1]["child_of"] = None

    issues = validate(_sol(m))
    assert any(
        i.code == "REF_UNKNOWN" and i.path == "entities.0.fields.7.of" for i in issues
    )


def test_link_unknown_entity():
    def m(d):
        d["entities"][0]["fields"].append(
            {"name": "peer", "type": "link", "to": ["ghost"]}
        )

    assert _codes(validate(_sol(m))) == ["REF_UNKNOWN"]


def test_transition_unknown_role_and_report_entity_and_role_key():
    def m(d):
        d["workflow"]["transitions"][0]["roles"] = ["ghost"]
        d["reports"][0]["entity"] = "ghost"
        d["roles"]["manager"]["ghost_entity"] = ["read"]

    issues = validate(_sol(m))
    paths = {i.path for i in issues if i.code == "REF_UNKNOWN"}
    assert "workflow.0.transitions.0.roles" in paths
    assert "reports.0.entity" in paths
    assert "roles.manager.ghost_entity" in paths


def test_unknown_cover_token():
    def m(d):
        d["acceptance_tests"][0]["covers"] = ["R1", "bogus"]

    issues = validate(_sol(m))
    assert _codes(issues) == ["REF_UNKNOWN"]
    assert issues[0].path == "acceptance_tests.0.covers"


def test_duplicates():
    def m(d):
        d["entities"][0]["fields"].append({"name": "driver", "type": "text"})
        d["rules"].append({"id": "R1", "text": "dup"})
        d["workflow"]["states"].append("draft")

    issues = [i for i in validate(_sol(m)) if i.code == "DUPLICATE_NAME"]
    assert len(issues) == 3


def test_wf_no_initial():
    def m(d):
        d["workflow"]["initial"] = "nowhere"

    assert "WF_NO_INITIAL" in _codes(validate(_sol(m)))


def test_wf_unreachable():
    def m(d):
        d["workflow"]["transitions"].pop(0)

    issues = validate(_sol(m))
    unreachable = [i for i in issues if i.code == "WF_UNREACHABLE"]
    assert any("pending_security" in i.message for i in unreachable)


def test_wf_dead_end():
    def m(d):
        d["workflow"]["final_states"] = ["rejected"]

    issues = validate(_sol(m))
    dead = [i for i in issues if i.code == "WF_DEAD_END"]
    assert len(dead) == 1 and "closed" in dead[0].message


def test_trace_rule():
    def m(d):
        d["acceptance_tests"] = [a for a in d["acceptance_tests"] if a["id"] != "AT-03"]

    issues = validate(_sol(m))
    assert _codes(issues) == ["TRACE_RULE"]
    assert "R2" in issues[0].message


def test_trace_transition():
    def m(d):
        d["acceptance_tests"][1]["covers"] = ["workflow:approve"]

    issues = validate(_sol(m))
    tt = [i for i in issues if i.code == "TRACE_TRANSITION"]
    assert {("submit" in i.message, "close" in i.message) for i in tt} >= {
        (True, False)
    }
    assert not any("approve" in i.message for i in tt)
    assert not any("reject" in i.message for i in tt)


def test_trace_permission_and_report():
    def m(d):
        d["acceptance_tests"][5]["covers"] = ["permissions:manager"]
        d["acceptance_tests"][4]["covers"] = ["R1"]

    issues = validate(_sol(m))
    tp = [i for i in issues if i.code == "TRACE_PERMISSION"]
    assert {("store_user" in i.message) or ("security" in i.message) for i in tp} == {
        True
    }
    assert len(tp) == 2
    # uncovered reports use TRACE_RULE (the brief defines no separate report code)
    assert any(i.code == "TRACE_RULE" and "gate_register" in i.message for i in issues)


def test_capability():
    def m(d):
        pass

    issues = validate(_sol(m), {"field_types": ["text"]})
    cap = [i for i in issues if i.code == "CAPABILITY"]
    assert cap and any("decimal" in i.message for i in cap)
    assert validate(_sol(m), None) == []


def test_cli_validate_dir_and_file(tmp_path):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "solution.yaml").write_text(
        (FIX / "gate_pass.yaml").read_text()
    )
    r = CliRunner().invoke(app, ["validate", str(tmp_path)])
    assert r.exit_code == 0 and "OK: no issues" in r.output
    r = CliRunner().invoke(app, ["validate", str(FIX / "gate_pass.yaml")])
    assert r.exit_code == 0


def test_cli_validate_issues_and_load_error(tmp_path):
    data = yaml.safe_load((FIX / "gate_pass.yaml").read_text())
    data["workflow"]["transitions"].pop(0)
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data))
    r = CliRunner().invoke(app, ["validate", str(p)])
    assert r.exit_code == 1 and "WF_UNREACHABLE" in r.output
    r = CliRunner().invoke(app, ["validate", str(FIX / "bad_unknown_key.yaml")])
    assert r.exit_code == 1 and r.output.strip()
