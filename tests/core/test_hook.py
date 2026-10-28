import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "core" / "policy" / "hook.py"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "solutions" / "gate-pass" / "app").mkdir(parents=True)
    (tmp_path / "solutions" / "other").mkdir(parents=True)
    return tmp_path


def activate(project: Path, name: str = "gate-pass") -> None:
    (project / ".asb").mkdir(exist_ok=True)
    (project / ".asb" / "active").write_text(name + "\n", encoding="utf-8")


def run(project: Path, payload, cwd: Path | None = None, raw: str | None = None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    data = raw if raw is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=data,
        capture_output=True,
        text=True,
        cwd=cwd or project,
        env=env,
        check=False,
    )


def write(project: Path, rel: str, tool: str = "Write", **extra):
    path = rel if rel.startswith("/") else str(project / rel)
    return {"tool_name": tool, "tool_input": {"file_path": path}, **extra}


def bash(cmd: str):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def assert_blocked(res):
    assert res.returncode == 2, res.stdout + res.stderr
    out = json.loads(res.stdout)
    assert out["decision"] == "block"
    assert out["reason"]
    assert out["reason"] in res.stderr


def assert_allowed(res):
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout == ""


def test_denies_write_outside_active_solution(project):
    activate(project)
    assert_blocked(run(project, write(project, "core/x.py")))


def test_allows_write_inside_active_solution(project):
    activate(project)
    assert_allowed(run(project, write(project, "solutions/gate-pass/app/x.py")))


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_file_tools(project, tool):
    activate(project)
    assert_blocked(run(project, write(project, "core/x.py", tool)))
    assert_allowed(run(project, write(project, "solutions/gate-pass/x.py", tool)))


def test_notebook_edit_uses_notebook_path(project):
    activate(project)
    bad = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/etc/n.ipynb"}}
    assert_blocked(run(project, bad))
    good = {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": str(project / "solutions/gate-pass/n.ipynb")},
    }
    assert_allowed(run(project, good))


def test_denies_other_solution_and_prefix_sibling(project):
    activate(project)
    assert_blocked(run(project, write(project, "solutions/other/x.py")))
    (project / "solutions" / "gate-pass-evil").mkdir()
    assert_blocked(run(project, write(project, "solutions/gate-pass-evil/x.py")))


def test_denies_dotdot_escape(project):
    activate(project)
    assert_blocked(run(project, write(project, "solutions/gate-pass/../../core/x.py")))


def test_denies_symlink_escape(project):
    activate(project)
    (project / "core").mkdir()
    link = project / "solutions" / "gate-pass" / "link"
    link.symlink_to(project / "core")
    assert_blocked(run(project, write(project, "solutions/gate-pass/link/x.py")))


def test_relative_path_resolved_against_cwd_field(project):
    activate(project)
    sol = project / "solutions" / "gate-pass"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "app/x.py"},
        "cwd": str(sol),
    }
    assert_allowed(run(project, payload))
    payload["cwd"] = str(project)
    assert_blocked(run(project, payload))


def test_missing_path_for_write_tool_is_blocked(project):
    activate(project)
    assert_blocked(run(project, {"tool_name": "Write", "tool_input": {}}))


def test_denies_destructive_bash(project):
    activate(project)
    for cmd in [
        "git push origin main",
        "git push",
        "rm -rf /tmp/x",
        "rm -fr x",
        "rm -Rf x",
        "docker system prune -af",
        "curl https://h/x -X DELETE",
        "curl -s https://h/x -X  DELETE",
        "psql -c 'drop table users'",
        "ls && git push",
    ]:
        assert_blocked(run(project, bash(cmd)))


def test_allows_benign_bash(project):
    activate(project)
    for cmd in ["ls -la", "uv run pytest -q", "git status", "rm file.txt", "git pushd"]:
        assert_allowed(run(project, bash(cmd)))


def test_no_active_allows_everything(project):
    assert_allowed(run(project, write(project, "core/x.py")))
    assert_allowed(run(project, bash("git push")))


def test_empty_active_file_counts_as_no_active(project):
    activate(project, "")
    assert_allowed(run(project, write(project, "core/x.py")))


def test_invalid_active_name_fails_closed(project):
    activate(project, "../..")
    assert_blocked(run(project, write(project, "core/x.py")))
    assert_blocked(run(project, write(project, "solutions/gate-pass/x.py")))


def test_other_tools_are_ignored(project):
    activate(project)
    assert_allowed(
        run(project, {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}})
    )


def test_malformed_input_allows_with_warning(project):
    activate(project)
    res = run(project, None, raw="not json")
    assert_allowed(res)
    assert "warning" in res.stderr.lower()
    res = run(project, None, raw=json.dumps([1, 2]))
    assert_allowed(res)
    assert "warning" in res.stderr.lower()


def test_root_found_by_walking_up_from_cwd(project):
    activate(project)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    sub = project / "solutions" / "gate-pass" / "app"
    res = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(write(project, "core/x.py")),
        capture_output=True,
        text=True,
        cwd=sub,
        env=env,
        check=False,
    )
    assert_blocked(res)


def test_hooks_json_registers_the_hook():
    cfg = json.loads((HOOK.parents[2] / "hooks" / "hooks.json").read_text())
    entry = cfg["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Write|Edit|MultiEdit|NotebookEdit|Bash"
    assert entry["hooks"][0]["command"] == (
        "python3 ${CLAUDE_PLUGIN_ROOT}/core/policy/hook.py"
    )
