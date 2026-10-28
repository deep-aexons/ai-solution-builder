import sys

from typer.testing import CliRunner

from asb.cli import app
from asb.connector import AuthFailed, Connector, ConnectorError
from asb.discover import discover
from asb.model import External, Solution
from asb.status import load_status, new_solution


class FakeConnector:
    def __init__(self, kinds=None, version="v1.2", inspect_exc=None, list_exc=None):
        self._kinds = kinds if kinds is not None else {}
        self._version = version
        self._inspect_exc = inspect_exc
        self._list_exc = list_exc or {}

    def inspect(self):
        if self._inspect_exc:
            raise self._inspect_exc
        return {"version": self._version, "kinds": self._kinds}

    def get(self, kind, id):
        return {}

    def list(self, kind, filters=None, fields=None, limit=50):
        if kind in self._list_exc:
            raise self._list_exc[kind]
        return [{"name": str(i)} for i in range(min(limit, 3))]

    def create_draft(self, kind, data):
        return {}


def _solution(externals):
    return Solution.model_construct(
        solution="demo",
        external=[External(name=n, kind=k, access=a) for n, k, a in externals],
    )


def test_fake_is_connector():
    assert isinstance(FakeConnector(), Connector)


def test_all_kinds_ok_no_gaps():
    conn = FakeConnector(kinds={"item": {"doctype": "Thing", "fields": ["a", "b"]}})
    md = discover(_solution([("item", "item", "read")]), conn)
    assert md.startswith("# Discovery — demo")
    assert "v1.2" in md
    assert "| item | item | Thing | 2 | 3 | ok |" in md
    assert "None — read only" in md
    gaps = md.split("## Gaps")[1].split("## Notes")[0]
    assert "None" in gaps


def test_missing_kind_is_gap():
    md = discover(_solution([("sup", "supplier", "read")]), FakeConnector())
    assert "gap: kind not found" in md
    assert "- sup" in md.split("## Gaps")[1]


def test_inspect_kind_error_and_zero_fields_are_gaps():
    conn = FakeConnector(
        kinds={
            "a": {"doctype": "A", "fields": [], "error": "boom"},
            "b": {"doctype": "B", "fields": []},
        }
    )
    md = discover(_solution([("a", "a", "read"), ("b", "b", "read")]), conn)
    assert "gap: boom" in md
    assert "gap: no fields reported" in md


def test_list_error_is_gap_not_raised():
    conn = FakeConnector(
        kinds={"item": {"doctype": "Thing", "fields": ["a"]}},
        list_exc={"item": ConnectorError("denied")},
    )
    md = discover(_solution([("item", "item", "read")]), conn)
    assert "gap: list failed: denied" in md


def test_write_access_listed():
    conn = FakeConnector(kinds={"item": {"doctype": "Thing", "fields": ["a"]}})
    md = discover(_solution([("item", "item", "write:create_item")]), conn)
    section = md.split("## Write access requested")[1].split("## Gaps")[0]
    assert "item" in section and "write:create_item" in section


def test_auth_failed_reported():
    conn = FakeConnector(inspect_exc=AuthFailed("bad key"))
    md = discover(_solution([("item", "item", "read")]), conn)
    assert "Connection failed: AuthFailed: bad key" in md
    assert "not checked" in md


# ---- CLI -------------------------------------------------------------

FAKE_INIT = """
import os
from asb.connector import AuthFailed

class FakeConn:
    def __init__(self, allowed_writes):
        self.allowed_writes = allowed_writes
    def inspect(self):
        if os.environ.get("FAKE_FAIL"):
            raise AuthFailed("rejected")
        return {"version": "9.9", "kinds": {"item": {"doctype": "Thing", "fields": ["x"]}}}
    def get(self, kind, id):
        return {}
    def list(self, kind, filters=None, fields=None, limit=50):
        return [{}]
    def create_draft(self, kind, data):
        return {}
    def __repr__(self):
        return "FakeConn()"

def from_env(allowed_writes=frozenset()):
    assert allowed_writes == frozenset()
    return FakeConn(allowed_writes)
"""


def _setup(tmp_path, monkeypatch, connector="fake"):
    d = tmp_path / "connectors" / "fake"
    (d / "asb_fake_t13").mkdir(parents=True)
    (d / "connector.yaml").write_text(
        "name: fake\nentry: asb_fake_t13\nkinds:\n  item: Thing\n"
    )
    (d / "asb_fake_t13" / "__init__.py").write_text(FAKE_INIT)
    new_solution(tmp_path, "demo", "p", connector)
    monkeypatch.setattr(sys, "path", list(sys.path))
    sys.modules.pop("asb_fake_t13", None)


def _run(tmp_path, *args):
    return CliRunner().invoke(app, ["discover", "demo", "--root", str(tmp_path), *args])


def test_cli_discover_with_kind_marks_done(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = _run(tmp_path, "--kind", "item")
    assert r.exit_code == 0, r.output
    md = (tmp_path / "solutions/demo/discovery.md").read_text()
    assert "9.9" in md and "| item | item | Thing | 1 | 1 | ok |" in md
    assert load_status(tmp_path / "solutions/demo").stages["discovery"] == "done"
    assert "\tdiscover\t" in (tmp_path / "solutions/demo/audit.log").read_text()


def test_cli_discover_gap_still_done_with_warning(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = _run(tmp_path, "--kind", "supplier")
    assert r.exit_code == 0, r.output
    assert "1 gap" in r.output
    assert load_status(tmp_path / "solutions/demo").stages["discovery"] == "done"


def test_cli_auth_failed_not_done(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_FAIL", "1")
    r = _run(tmp_path, "--kind", "item")
    assert r.exit_code == 1
    assert "Connection failed" in r.output
    md = (tmp_path / "solutions/demo/discovery.md").read_text()
    assert "Connection failed: AuthFailed: rejected" in md
    assert load_status(tmp_path / "solutions/demo").stages["discovery"] == "todo"


def test_cli_no_connector(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, connector=None)
    r = _run(tmp_path, "--kind", "item")
    assert r.exit_code == 1
    assert "no connector configured for demo" in r.output


def test_cli_no_design_no_kind(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = _run(tmp_path)
    assert r.exit_code == 1
    assert "--kind" in r.output
