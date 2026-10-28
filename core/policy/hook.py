#!/usr/bin/env python3
"""Claude Code PreToolUse hook: confine the AI to the active solution.

Reads the hook JSON from stdin. With `<root>/.asb/active` present:
- Write/Edit/MultiEdit/NotebookEdit may only touch `<root>/solutions/<active>/`, and
  never the protected files (status.json, audit.log, exceptions.yaml,
  app/.asb-manifest.json) or anything under `<root>/.asb/`.
- Bash commands may not match the `deny_commands` regexes of the sibling policy.yaml
  (an embedded copy is used when PyYAML or the file is unavailable).
A denial prints {"decision": "block", "reason": ...} on stdout, the reason on stderr,
appends a `hook-block` line to the solution's audit.log, and exits 2. Any unexpected
error blocks while a solution is active (fail closed). Without an active solution
everything is allowed (builder development).

This is a guardrail, not a sandbox: Bash can still write to arbitrary paths through
redirects, interpreters or tools the deny list does not know, and MCP tools are not
covered by the hook matcher.
Standard library only; PyYAML is imported lazily.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

POLICY = Path(__file__).resolve().parent / "policy.yaml"
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
NAME = re.compile(r"[a-z][a-z0-9-]*")
PROTECTED = ("status.json", "audit.log", "exceptions.yaml", "app/.asb-manifest.json")
# Embedded copy of core/policy/policy.yaml deny_commands (kept in sync by a test).
DEFAULT_DENY = [
    "\\brm\\b(?=[^;|&\\n]*\\s(?:-[a-z]*r[a-z]*|--recursive)(?:\\s|$))(?=[^;|&\\n]*\\s(?:-[a-z]*f[a-z]*|--force)(?:\\s|$))",
    "\\bgit\\b.*\\bpush\\b",
    "\\$\\{?\\w+\\}?\\s+push\\b",
    "\\bdocker\\b.*\\bsystem\\s+prune\\b",
    "curl\\b.*(-X|--request)[\\s=]*['\"]?DELETE",
    "\\bfind\\b.*\\s-delete\\b",
    "\\bDROP\\s+(TABLE|DATABASE)\\b",
    "\\basb\\s+(approve|use)\\b",
    "-m\\s+asb\\b.*\\b(approve|use)\\b",
    "(?<![\\w.])\\.asb(?![\\w.-])",
    "\\A(?=.*(?:status\\.json|audit\\.log|exceptions\\.yaml|\\.asb-manifest\\.json))(?=.*(?:(?<!\\d)>(?!&)|\\btee\\b|\\bsed\\b[^\\n]*\\s-[a-z]*i|\\bmv\\b|\\bcp\\b|\\brm\\b|\\btruncate\\b))",
]


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
    sol = (root / "solutions" / active).resolve()
    if not resolved.is_relative_to(sol):
        raise Block(
            f"write to {resolved} denied: only solutions/{active}/ may be changed "
            f"while '{active}' is the active solution"
        )
    if resolved.is_relative_to((root / ".asb").resolve()):
        raise Block(f"write to {resolved} denied: .asb/ is managed by the asb tool")
    for rel in PROTECTED:
        if resolved == (sol / rel).resolve():
            raise Block(f"write to {resolved} denied: protected file ({rel})")


def deny_patterns() -> list[str]:
    try:
        import yaml

        policy = yaml.safe_load(POLICY.read_text(encoding="utf-8")) or {}
        patterns = [str(p) for p in policy.get("deny_commands") or []]
        if patterns:
            return patterns
    except Exception as exc:  # noqa: BLE001
        print(f"warning: using embedded deny list ({exc})", file=sys.stderr)
    return DEFAULT_DENY


def check_bash(data: dict) -> None:
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return
    for pattern in deny_patterns():
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


def audit(root: Path, data: dict, reason: str) -> None:
    """Append a hook-block line to the active solution's audit.log (best effort)."""
    try:
        active = active_solution(root)
        log = root / "solutions" / str(active) / "audit.log"
        if active is None or not log.parent.is_dir():
            return
        stamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        detail = f"{data.get('tool_name')}: {reason}".replace("\t", " ")
        detail = detail.replace("\n", " ")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp}\thook-block\t{detail}\n")
    except Exception:  # noqa: BLE001, S110
        pass


def is_active(root: Path) -> bool:
    try:
        return (root / ".asb" / "active").read_text(encoding="utf-8").strip() != ""
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001
        return True  # unreadable: assume active (fail closed)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")  # noqa: TRY004
    except ValueError as exc:
        print(f"warning: hook input ignored (malformed): {exc}", file=sys.stderr)
        return 0
    try:
        start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
        root = find_root(start.resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"warning: hook could not locate the project: {exc}", file=sys.stderr)
        return 0
    if root is None:
        return 0
    try:
        decide(data, root)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, Block):
            reason = str(exc)
        elif is_active(root):
            reason = f"hook error, blocking to be safe: {type(exc).__name__}: {exc}"
        else:
            print(f"warning: hook error ignored: {exc}", file=sys.stderr)
            return 0
        audit(root, data, reason)
        print(json.dumps({"decision": "block", "reason": reason}))
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
