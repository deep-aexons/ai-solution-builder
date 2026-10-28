import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from asb.cli import app
from asb.connector import (
    AuthFailed,
    Connector,
    ConnectorError,
    NotFound,
    Unavailable,
    WriteNotApproved,
)
from asb.model import PERMISSIONS, load_solution
from asb.plugins import (
    CheckResult,
    GenerateResult,
    VerifyResult,
    load_connector,
    load_pack,
    read_connector_info,
)
from asb.status import new_solution
from asb.validate import validate

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures"
FIELD_TYPES = {
    "text", "number", "decimal", "money", "date", "datetime", "choice",
    "boolean", "attachment", "link", "external_ref", "table",
}  # fmt: skip


def _gate_pass_dict():
    return yaml.safe_load((FIX / "gate_pass.yaml").read_text())


def test_load_sidecar_pack():
    pack = load_pack(REPO, "sidecar-django")
    assert pack.name == "sidecar-django"
    assert pack.path == REPO / "packs" / "sidecar-django"
    caps = pack.capabilities
    assert set(caps["field_types"]) == FIELD_TYPES
    assert "external_ref" in caps["field_types"]
    assert set(caps["permissions"]) == set(PERMISSIONS)
    assert caps["workflow"] is True and caps["reports"] is True


def test_pack_methods_proxy_to_module():
    pack = load_pack(REPO, "sidecar-django")
    assert pack.module.generate.__module__ == "asb_sidecar.generate"
    with pytest.raises(NotImplementedError, match="later task"):
        pack.verify(None, Path("."))


def test_unknown_pack_names_path(tmp_path):
    with pytest.raises(FileNotFoundError) as ei:
        load_pack(tmp_path, "nope")
    assert str(tmp_path / "packs" / "nope" / "pack.yaml") in str(ei.value)


def test_unknown_connector_names_path(tmp_path):
    with pytest.raises(FileNotFoundError) as ei:
        read_connector_info(tmp_path, "nope")
    assert str(tmp_path / "connectors" / "nope" / "connector.yaml") in str(ei.value)


def test_gate_pass_valid_with_sidecar_capabilities():
    caps = load_pack(REPO, "sidecar-django").capabilities
    assert validate(load_solution(FIX / "gate_pass.yaml"), caps) == []


def test_erpnext_connector_yaml_kinds():
    info = read_connector_info(REPO, "erpnext")
    assert info.name == "erpnext"
    assert info.path == REPO / "connectors" / "erpnext"
    assert info.module is None
    assert info.kinds["outbound_shipment"] == "Delivery Note"
    assert info.kinds["inbound_receipt"] == "Purchase Receipt"
    assert {"customer", "supplier", "item"} <= set(info.kinds)


def _fake_connector(root: Path, name: str, pkg: str):
    d = root / "connectors" / name
    (d / pkg).mkdir(parents=True)
    (d / "connector.yaml").write_text(
        f"name: {name}\nentry: {pkg}\nkinds:\n  item: Thing\n"
    )
    (d / pkg / "__init__.py").write_text("MARK = 42\n")


def test_load_connector_imports_entry(tmp_path):
    _fake_connector(tmp_path, "fake", "asb_fake_t5")
    try:
        info = load_connector(tmp_path, "fake")
        assert info.module.MARK == 42
        assert info.kinds == {"item": "Thing"}
        assert str(tmp_path / "connectors" / "fake") in sys.path
    finally:
        sys.modules.pop("asb_fake_t5", None)
        sys.path[:] = [p for p in sys.path if "fake" not in p or "connectors" not in p]


def test_load_pack_imports_fake_pack(tmp_path):
    d = tmp_path / "packs" / "fp"
    (d / "asb_fp_t5").mkdir(parents=True)
    (d / "pack.yaml").write_text(
        "name: fp\nentry: asb_fp_t5\nfield_types: [text]\n"
        "workflow: false\nreports: false\npermissions: [read]\n"
    )
    (d / "asb_fp_t5" / "__init__.py").write_text(
        "def generate(solution, solution_dir):\n    return ('gen', solution_dir)\n"
        "def verify(solution, solution_dir):\n    return ('ver', solution_dir)\n"
    )
    try:
        pack = load_pack(tmp_path, "fp")
        assert pack.capabilities == {
            "field_types": ["text"],
            "workflow": False,
            "reports": False,
            "permissions": ["read"],
        }
        assert pack.generate("s", Path("x")) == ("gen", Path("x"))
        assert pack.verify("s", Path("y")) == ("ver", Path("y"))
    finally:
        sys.modules.pop("asb_fp_t5", None)
        sys.path[:] = [p for p in sys.path if str(d) != p]


def test_result_dataclasses():
    g = GenerateResult(written=["a"], skipped_ai_owned=["b"])
    v = VerifyResult(checks=[CheckResult("t", "pass", "ok")])
    assert g.written == ["a"] and v.checks[0].status == "pass"


def test_connector_protocol_and_errors():
    class Good:
        def inspect(self):
            return {}

        def get(self, kind, id):
            return {}

        def list(self, kind, filters=None, fields=None, limit=50):
            return []

        def create_draft(self, kind, data):
            return {}

    class Bad:
        def inspect(self):
            return {}

    assert isinstance(Good(), Connector)
    assert not isinstance(Bad(), Connector)
    for exc in (NotFound, Unavailable, AuthFailed, WriteNotApproved):
        assert issubclass(exc, ConnectorError)
    for forbidden in ("delete", "submit", "cancel"):
        assert not hasattr(Connector, forbidden)


def test_connector_module_is_stdlib_only():
    import ast

    src = (REPO / "core/tool/asb/connector.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            continue
        for m in mods:
            assert m.split(".")[0] in sys.stdlib_module_names, m


def test_validate_permission_capability():
    sol = load_solution(FIX / "gate_pass.yaml")
    issues = validate(sol, {"permissions": ["read", "create"]})
    cap = [i for i in issues if i.code == "CAPABILITY"]
    assert any("approve" in i.message for i in cap)
    assert any("update_own_draft" in i.message for i in cap)


def test_validate_workflow_and_reports_capability():
    sol = load_solution(FIX / "gate_pass.yaml")
    issues = validate(sol, {"workflow": False, "reports": False})
    msgs = [i.message for i in issues if i.code == "CAPABILITY"]
    assert any("workflow" in m for m in msgs)
    assert any("report" in m for m in msgs)
    assert validate(sol, {"workflow": True, "reports": True}) == []


def _setup_solution(tmp_path, pack="sidecar-django", data=None):
    sol_dir = new_solution(tmp_path, "gp", pack, None)
    (sol_dir / "design" / "solution.yaml").write_text(
        yaml.safe_dump(data or _gate_pass_dict())
    )
    return sol_dir


def test_cli_validate_uses_pack_capabilities(tmp_path):
    sol_dir = _setup_solution(tmp_path)
    r = CliRunner().invoke(app, ["validate", str(sol_dir), "--root", str(REPO)])
    assert r.exit_code == 0 and "OK" in r.output


def test_cli_validate_flags_capability_issue(tmp_path):
    root = tmp_path / "root"
    d = root / "packs" / "tiny"
    (d / "asb_tiny_t5").mkdir(parents=True)
    (d / "pack.yaml").write_text(
        "name: tiny\nentry: asb_tiny_t5\nfield_types: [text]\n"
        "workflow: true\nreports: true\npermissions: [read]\n"
    )
    (d / "asb_tiny_t5" / "__init__.py").write_text("")
    sol_dir = _setup_solution(root, pack="tiny")
    try:
        r = CliRunner().invoke(app, ["validate", str(sol_dir), "--root", str(root)])
    finally:
        sys.modules.pop("asb_tiny_t5", None)
        sys.path[:] = [p for p in sys.path if str(d) != p]
    assert r.exit_code == 1 and "CAPABILITY" in r.output


def test_cli_validate_unknown_pack_errors(tmp_path):
    sol_dir = _setup_solution(tmp_path, pack="ghost")
    r = CliRunner().invoke(app, ["validate", str(sol_dir), "--root", str(tmp_path)])
    assert r.exit_code == 1 and "pack.yaml" in r.output


def test_cli_validate_without_status_skips_capabilities(tmp_path):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "solution.yaml").write_text(
        (FIX / "gate_pass.yaml").read_text()
    )
    r = CliRunner().invoke(app, ["validate", str(tmp_path)])
    assert r.exit_code == 0
