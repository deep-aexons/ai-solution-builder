import sys
from pathlib import Path

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
    conn = FakeConnector(kinds={"item": {"document": "Thing", "fields": ["a", "b"]}})
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
            "a": {"document": "A", "fields": [], "error": "boom"},
            "b": {"document": "B", "fields": []},
        }
    )
    md = discover(_solution([("a", "a", "read"), ("b", "b", "read")]), conn)
    assert "gap: boom" in md
    assert "gap: no fields reported" in md


def test_list_error_is_gap_not_raised():
    conn = FakeConnector(
        kinds={"item": {"document": "Thing", "fields": ["a"]}},
        list_exc={"item": ConnectorError("denied")},
    )
    md = discover(_solution([("item", "item", "read")]), conn)
    assert "gap: list failed: ConnectorError: denied" in md


def test_write_access_listed():
    conn = FakeConnector(kinds={"item": {"document": "Thing", "fields": ["a"]}})
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
        if os.environ.get("FAKE_MALFORMED"):
            return ["nope"]
        return {"version": "9.9", "kinds": {"item": {"document": "Thing", "fields": ["x"]}}}
    def get(self, kind, id):
        return {}
    def list(self, kind, filters=None, fields=None, limit=50):
        return [{}]
    def create_draft(self, kind, data):
        return {}
    def __repr__(self):
        return "FakeConn()"

def from_env(allowed_writes=frozenset()):
    if os.environ.get("FAKE_ENV_BOOM"):
        raise KeyError("ASB_ERP_URL")
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
    monkeypatch.setitem(sys.modules, "asb_fake_t13", sys.modules.get("asb_fake_t13"))
    monkeypatch.delitem(sys.modules, "asb_fake_t13")


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


def test_non_connector_exceptions_do_not_escape():
    class Boom(FakeConnector):
        def list(self, kind, filters=None, fields=None, limit=50):
            raise KeyError("zzz")

    conn = Boom(kinds={"item": {"document": "T", "fields": ["a"]}})
    md = discover(_solution([("item", "item", "read")]), conn)
    assert "gap: list failed: KeyError" in md

    class BadInspect(FakeConnector):
        def inspect(self):
            raise AttributeError("no attr")

    md = discover(_solution([("item", "item", "read")]), BadInspect())
    assert "Connection failed: AttributeError: no attr" in md
    assert "not checked" in md


def test_malformed_inspect_results():
    md = discover(_solution([("a", "a", "read")]), FakeConnector(kinds=["x"]))
    assert "gap: kind not found" in md
    conn = FakeConnector(kinds={"a": "str", "b": {"document": "B", "fields": 5}})
    md = discover(_solution([("a", "a", "read"), ("b", "b", "read")]), conn)
    assert "gap: malformed inspect entry" in md
    assert "gap: malformed fields" in md

    class NotMap(FakeConnector):
        def inspect(self):
            return ["nope"]

    md = discover(_solution([("a", "a", "read")]), NotMap())
    assert "Connection failed: TypeError" in md


def test_no_connector_no_error_guard():
    from asb.discover import run_discovery

    rep = run_discovery(_solution([("a", "a", "read")]), None)
    assert not rep.connected


def test_markdown_injection_neutralised():
    evil = "1.0\n## Gaps\n- fake `x` \\ y"
    conn = FakeConnector(
        version=evil, kinds={"item": {"document": "T`|\n# H", "fields": ["a"]}}
    )
    md = discover(_solution([("item", "item", "read")]), conn)
    assert md.count("\n## Gaps") == 1
    assert "\n# H" not in md
    assert "\\`x\\`" in md and "\\\\ y" in md
    md = discover(
        _solution([("item", "item", "read")]),
        FakeConnector(inspect_exc=AuthFailed("a\n## Gaps\n- x")),
    )
    assert md.count("\n## Gaps") == 1


def test_cli_from_env_non_connector_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_ENV_BOOM", "1")
    r = _run(tmp_path, "--kind", "item")
    assert r.exit_code == 1
    assert "Connection failed: KeyError" in r.output
    assert (
        "Connection failed: KeyError"
        in (tmp_path / "solutions/demo/discovery.md").read_text()
    )


def test_cli_malformed_inspect(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MALFORMED", "1")
    r = _run(tmp_path, "--kind", "item")
    assert r.exit_code == 1
    assert "Connection failed: TypeError" in r.output


def test_cli_failure_resets_previous_done(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert _run(tmp_path, "--kind", "item").exit_code == 0
    assert load_status(tmp_path / "solutions/demo").stages["discovery"] == "done"
    monkeypatch.setenv("FAKE_FAIL", "1")
    assert _run(tmp_path, "--kind", "item").exit_code == 1
    assert load_status(tmp_path / "solutions/demo").stages["discovery"] == "todo"


def test_cli_invalid_kind_name(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = _run(tmp_path, "--kind", "Bad-Name")
    assert r.exit_code == 1
    assert r.output.startswith("error:") and "Bad-Name" in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_cli_kind_ignored_with_design_warns(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import shutil

    fixture = Path(__file__).parent.parent / "fixtures" / "gate_pass.yaml"
    shutil.copy(fixture, tmp_path / "solutions/demo/design/solution.yaml")
    r = _run(tmp_path, "--kind", "item")
    assert "--kind ignored" in r.output
