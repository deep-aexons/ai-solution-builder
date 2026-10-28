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


PROTECTED = [
    "solutions/gate-pass/status.json",
    "solutions/gate-pass/audit.log",
    "solutions/gate-pass/exceptions.yaml",
    "solutions/gate-pass/app/.asb-manifest.json",
    ".asb/active",
    ".asb/manifests/gate-pass.sha256",
]


@pytest.mark.parametrize("rel", PROTECTED)
@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_protected_files_cannot_be_written(project, rel, tool):
    activate(project)
    assert_blocked(run(project, write(project, rel, tool)))


def test_protected_file_via_symlink_is_blocked(project):
    activate(project)
    sol = project / "solutions" / "gate-pass"
    (sol / "alias.json").symlink_to(sol / "status.json")
    assert_blocked(run(project, write(project, "solutions/gate-pass/alias.json")))


def test_notebook_cannot_touch_protected(project):
    activate(project)
    payload = {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": str(project / "solutions/gate-pass/audit.log")},
    }
    assert_blocked(run(project, payload))


@pytest.mark.parametrize(
    "cmd",
    [
        'rm "-rf" x',
        "rm '-r' '-f' x",
        "ln -sf x solutions/gate-pass/status.json",
        "dd if=x of=solutions/gate-pass/audit.log",
        "sed --in-place s/a/b/ solutions/gate-pass/exceptions.yaml",
        "rm -r -f x",
        "rm -f -r x",
        "rm -rf x",
        "rm -fR x",
        "rm --recursive --force x",
        "rm --force --recursive x",
        "rm -r --force x",
        "RM -RF x",
        "git -C . push",
        "git --no-pager push origin",
        "git remote -v; git push",
        "GIT=git; $GIT push",
        "${GIT} push",
        "curl --request DELETE https://h/x",
        "curl -XDELETE https://h/x",
        "curl -X 'DELETE' https://h/x",
        "curl https://h/x --request=DELETE",
        "find . -name '*.py' -delete",
        "asb approve gate-pass design --by me",
        "uv run asb use other",
        "python -m asb.cli approve gate-pass design --by me",
        "cat .asb/active",
        "echo other > .asb/active",
        "cd .asb",
        "echo '{}' > solutions/gate-pass/status.json",
        "echo x >> solutions/gate-pass/audit.log",
        "echo x | tee solutions/gate-pass/audit.log",
        "sed -i 's/a/b/' solutions/gate-pass/status.json",
        "mv x solutions/gate-pass/exceptions.yaml",
        "cp x solutions/gate-pass/app/.asb-manifest.json",
        "rm solutions/gate-pass/audit.log",
        "truncate -s 0 solutions/gate-pass/audit.log",
        "docker  system   prune",
        "DROP DATABASE x",
    ],
)
def test_bash_evasions_are_blocked(project, cmd):
    activate(project)
    assert_blocked(run(project, bash(cmd)))


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -r build",
        "rm -f x.txt",
        "cat solutions/gate-pass/status.json",
        "grep x solutions/gate-pass/audit.log 2>&1",
        "uv run asb check gate-pass",
        "ls solutions/gate-pass/app/.asb-manifest.json",
        "curl -X GET https://h/x",
        "find . -name x",
        "git status && git diff",
    ],
)
def test_benign_commands_still_allowed(project, cmd):
    activate(project)
    assert_allowed(run(project, bash(cmd)))


def test_block_is_appended_to_audit_log(project):
    activate(project)
    log = project / "solutions" / "gate-pass" / "audit.log"
    log.write_text("", encoding="utf-8")
    assert_blocked(run(project, bash("git push")))
    assert_blocked(run(project, write(project, "core/x.py")))
    lines = log.read_text().splitlines()
    assert len(lines) == 2
    ts, event, detail = lines[0].split("\t")
    assert ts.endswith("Z")
    assert event == "hook-block"
    assert detail.startswith("Bash:")
    assert lines[1].split("\t")[2].startswith("Write:")


def test_no_audit_when_allowed_or_inactive(project):
    activate(project)
    log = project / "solutions" / "gate-pass" / "audit.log"
    log.write_text("", encoding="utf-8")
    assert_allowed(run(project, bash("ls")))
    assert log.read_text() == ""


def test_unexpected_error_blocks_when_active_and_allows_otherwise(project):
    bad = {"tool_name": "Write", "tool_input": {"file_path": "x"}, "cwd": "bad\x00dir"}
    activate(project)
    res = run(project, bad)
    assert_blocked(res)
    assert "hook error" in res.stdout
    (project / ".asb" / "active").unlink()
    res = run(project, bad)
    assert_allowed(res)


def test_missing_yaml_falls_back_to_embedded_deny_list(project, tmp_path):
    activate(project)
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "yaml.py").write_text("raise ImportError('no yaml')\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(CLAUDE_PROJECT_DIR=str(project), PYTHONPATH=str(fake))
    res = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(bash("git push")),
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
        check=False,
    )
    assert_blocked(res)
    assert "embedded" in res.stderr


def test_embedded_deny_list_matches_policy_yaml():
    import importlib.util

    import yaml

    spec = importlib.util.spec_from_file_location("asb_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    policy = yaml.safe_load((HOOK.parent / "policy.yaml").read_text())
    assert mod.DEFAULT_DENY == policy["deny_commands"]
