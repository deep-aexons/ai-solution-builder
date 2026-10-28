from pathlib import Path

import pytest
import yaml

from asb.model import ModelError, Solution, load_solution

FIX = Path(__file__).parent.parent / "fixtures"


def _load_dict(tmp_path, mutate):
    data = yaml.safe_load((FIX / "gate_pass.yaml").read_text())
    mutate(data)
    p = tmp_path / "solution.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_loads_gate_pass():
    sol = load_solution(FIX / "gate_pass.yaml")
    assert isinstance(sol, Solution)
    assert len(sol.entities) == 2
    assert len(sol.workflows) == 1
    assert len(sol.workflows[0].states) == 5
    assert sol.workflows[0].transitions[0].from_ == "draft"
    assert len(sol.roles) == 3
    assert len(sol.rules) == 2
    assert len(sol.acceptance_tests) == 6


def test_unknown_key_reports_path():
    with pytest.raises(ModelError) as exc:
        load_solution(FIX / "bad_unknown_key.yaml")
    assert "entities.0.fields.1.requird" in exc.value.issues[0]


def test_bad_field_type(tmp_path):
    p = _load_dict(
        tmp_path, lambda d: d["entities"][0]["fields"][0].update(type="string")
    )
    with pytest.raises(ModelError) as exc:
        load_solution(p)
    assert "entities.0.fields.0.type" in exc.value.issues[0]
    assert "external_ref" in exc.value.issues[0]


def test_bad_permission(tmp_path):
    p = _load_dict(tmp_path, lambda d: d["roles"]["manager"].update(gate_pass=["edit"]))
    with pytest.raises(ModelError) as exc:
        load_solution(p)
    assert "edit" in exc.value.issues[0]
    assert "roles.manager.gate_pass" in exc.value.issues[0]


@pytest.mark.parametrize(
    "key,idx,val", [("acceptance_tests", 0, "AT-1"), ("rules", 0, "r1")]
)
def test_bad_ids(tmp_path, key, idx, val):
    p = _load_dict(tmp_path, lambda d: d[key][idx].update(id=val))
    with pytest.raises(ModelError) as exc:
        load_solution(p)
    assert f"{key}.{idx}.id" in exc.value.issues[0]


def test_workflow_single_mapping_normalised(tmp_path):
    sol = load_solution(FIX / "gate_pass.yaml")
    assert sol.workflow == sol.workflows


def test_bad_name(tmp_path):
    p = _load_dict(tmp_path, lambda d: d["entities"][0].update(name="GatePass"))
    with pytest.raises(ModelError):
        load_solution(p)


def test_non_mapping_yaml(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ModelError):
        load_solution(p)
