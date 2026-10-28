#!/usr/bin/env python3
"""Claude Code PreToolUse hook: confine the AI to the active solution.

Reads the hook JSON from stdin. With `<root>/.asb/active` present, file-writing tools
may only touch `<root>/solutions/<active>/` and Bash commands may not match the
`deny_commands` regexes of the sibling policy.yaml. A denial prints
{"decision": "block", "reason": ...} on stdout, the reason on stderr, and exits 2.
Without an active solution everything is allowed (builder development).
Standard library plus PyYAML only.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml

POLICY = Path(__file__).resolve().parent / "policy.yaml"
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
NAME = re.compile(r"[a-z][a-z0-9-]*")


class Block(Exception):
    """Raised to deny the tool call."""


def find_root(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / ".asb").is_dir():
            return folder
    return None


def active_solution(root: Path) -> str | None:
    try:
        text = (root / ".asb" / "active").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise Block(f"cannot read .asb/active: {exc}") from exc
    if not text:
        return None
    if not NAME.fullmatch(text):
        raise Block(f"invalid active solution name in .asb/active: {text!r}")
    return text


def check_write(root: Path, active: str, data: dict, cwd: Path) -> None:
    tool_input = data.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target:
        raise Block(f"{data.get('tool_name')} without a file path is not allowed")
    path = Path(target)
    if not path.is_absolute():
        path = cwd / path
    resolved = path.resolve()  # collapses '..' and follows symlinks
    allowed = (root / "solutions" / active).resolve()
    if not resolved.is_relative_to(allowed):
        raise Block(
            f"write to {resolved} denied: only solutions/{active}/ may be changed "
            f"while '{active}' is the active solution"
        )


def check_bash(data: dict) -> None:
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return
    try:
        policy = yaml.safe_load(POLICY.read_text(encoding="utf-8")) or {}
        patterns = list(policy.get("deny_commands") or [])
    except (OSError, UnicodeDecodeError, yaml.YAMLError, AttributeError) as exc:
        raise Block(f"cannot load {POLICY.name}, refusing Bash: {exc}") from exc
    for pattern in patterns:
        try:
            hit = re.search(pattern, command, re.IGNORECASE | re.DOTALL)
        except (re.error, TypeError):
            print(f"warning: invalid deny pattern {pattern!r} ignored", file=sys.stderr)
            continue
        if hit:
            raise Block(f"command denied by policy (matches {pattern!r})")


def decide(data: dict, root: Path) -> None:
    active = active_solution(root)
    if active is None:
        return
    tool = data.get("tool_name")
    if tool in WRITE_TOOLS:
        cwd = data.get("cwd")
        base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
        check_write(root, active, data, base)
    elif tool == "Bash":
        check_bash(data)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")  # noqa: TRY004
    except ValueError as exc:
        print(f"warning: hook input ignored (malformed): {exc}", file=sys.stderr)
        return 0
    start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    root = find_root(start.resolve())
    if root is None:
        return 0
    try:
        decide(data, root)
    except Block as exc:
        reason = str(exc)
        print(json.dumps({"decision": "block", "reason": reason}))
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
