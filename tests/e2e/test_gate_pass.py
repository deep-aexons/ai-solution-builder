"""Gate Pass pilot: regenerate the committed solution from its design and verify it."""

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from asb_sidecar import generate, verify

from asb.connector import Connector, NotFound
from asb.discover import discover
from asb.model import load_solution

REPO = Path(__file__).parents[2]
SOLUTION = REPO / "solutions" / "gate-pass"
BROWSER_STACK = bool(
    shutil.which("npm") and importlib.util.find_spec("playwright") is not None
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ai_owned(app):
    """Committed backend .py files the generator did not write (not in its manifest)."""
    manifest = json.loads((app / ".asb-manifest.json").read_text())
    return sorted(
        p.relative_to(app).as_posix()
        for p in (app / "backend").rglob("*.py")
        if "__pycache__" not in p.parts
        and p.relative_to(app).as_posix() not in manifest
    )


def _recorded():
    spec = importlib.util.spec_from_file_location(
        "recorded_erpnext", REPO / "tests" / "e2e" / "fixtures" / "recorded_erpnext.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fixture_and_committed_design_are_identical():
    fixture = REPO / "tests" / "fixtures" / "gate_pass.yaml"
    assert fixture.read_bytes() == (SOLUTION / "design" / "solution.yaml").read_bytes()


def test_recorded_connector_behaves_like_a_connector():
    fake = _recorded().FakeConnector()
    assert isinstance(fake, Connector)
    assert len(fake.list("outbound_shipment", limit=2)) == 2
    assert fake.get("inbound_receipt", "PR-00003")["_state"] == "cancelled"
    with pytest.raises(NotFound):
        fake.get("outbound_shipment", "DN-NOPE")


def test_committed_discovery_is_the_recorded_sample_report():
    solution = load_solution(SOLUTION / "design" / "solution.yaml")
    report = discover(solution, _recorded().FakeConnector())
    body = report.split("\n", 1)[1].strip()
    text = (SOLUTION / "discovery.md").read_text()
    assert text.startswith(report.split("\n", 1)[0])
    assert text.rstrip().endswith(body)
    assert "Offline discovery from a recorded ERPNext sample" in text


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

    app, committed = sol_dir / "app", SOLUTION / "app"
    # drift: a fresh regeneration equals the committed generated files
    fresh = json.loads((app / ".asb-manifest.json").read_text())
    assert fresh == json.loads((committed / ".asb-manifest.json").read_text())
    stale = [rel for rel, sha in fresh.items() if _sha(committed / rel) != sha]
    assert stale == [], f"committed generated files drifted: {stale}"

    owned = _ai_owned(committed)
    assert "backend/rules/r1.py" in owned and "backend/tests/test_at_01.py" in owned
    for rel in owned:
        target = app / rel
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
