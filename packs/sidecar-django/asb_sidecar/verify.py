"""Stage 5 verifier: all automated evidence for a generated sidecar app.

The generated app is only ever run in subprocesses (pytest, manage.py, npm); the
only code run in this process is the Playwright driver in `ui_smoke`.
"""

from __future__ import annotations

import ast
import fnmatch
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asb.checks import load_policy, read_anchor, run_checks
from asb.model import Solution
from asb.plugins import CheckResult, VerifyResult
from asb.status import load_status

from .procutil import as_text, clean_env, first_line, run_group, tail
from .ui_smoke import check_ui_smoke

TESTS_TIMEOUT = 900
NPM_TIMEOUT = 600
MATRIX_FILES = {
    "permission_matrix": "test_permission_matrix",
    "workflow_matrix": "test_workflow_matrix",
    "reports": "test_reports_smoke",
}
# The generated pytest.ini's python_files; only these files can hold collected tests.
TEST_FILE_PATTERNS = ("tests.py", "test_*.py")
_NPM_NETWORK_CODE = re.compile(
    r"^npm (?:ERR!|error) code (ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ECONNREFUSED|ECONNRESET)\b",
    re.MULTILINE,
)


def _is_test_file(path: Path) -> bool:
    return any(fnmatch.fnmatch(path.name, p) for p in TEST_FILE_PATTERNS)


# pytest run ------------------------------------------------------------------------------


@dataclass
class Case:
    module: str  # dotted module path, e.g. tests.test_at_01
    name: str
    outcome: str  # passed | failed | error | skipped
    message: str = ""

    @property
    def file(self) -> str:
        return self.module.rsplit(".", 1)[-1]

    @property
    def func(self) -> str:
        return self.name.split("[", 1)[0]


@dataclass
class PytestRun:
    returncode: int | None
    output: str
    cases: list[Case] = field(default_factory=list)
    timed_out: bool = False
    junit_ok: bool = True


def _parse_junit(path: Path) -> list[Case] | None:
    try:
        root = ET.parse(path).getroot()  # our own pytest run's output
    except (OSError, ET.ParseError):
        return None
    cases: list[Case] = []
    for tc in root.iter("testcase"):
        parts = tc.get("classname", "").split(".")
        # drop a trailing test class name (CamelCase) from the module path
        while parts and parts[-1][:1].isupper():
            parts.pop()
        outcome, message = "passed", ""
        for child in tc:
            if child.tag in ("failure", "error", "skipped"):
                outcome = "failed" if child.tag == "failure" else child.tag
                message = (child.get("message") or child.text or "").strip()
                break
        cases.append(Case(".".join(parts), tc.get("name", ""), outcome, message))
    return cases


def run_pytest(backend: Path) -> PytestRun:
    with tempfile.TemporaryDirectory(prefix="asb-verify-") as tmp:
        junit = Path(tmp) / "junit.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-rs",
            f"--junitxml={junit}",
        ]
        try:
            proc = run_group(cmd, backend, TESTS_TIMEOUT, clean_env())
        except subprocess.TimeoutExpired as exc:
            return PytestRun(None, as_text(exc.output), timed_out=True)
        except OSError as exc:
            return PytestRun(None, f"cannot run pytest: {exc}", junit_ok=False)
        cases = _parse_junit(junit)
    return PytestRun(
        proc.returncode, proc.stdout, cases or [], junit_ok=cases is not None
    )


def _failures(cases: list[Case]) -> list[Case]:
    return [c for c in cases if c.outcome in ("failed", "error")]


def _describe_failures(bad: list[Case], limit: int = 10) -> str:
    lines = [
        f"{c.file}::{c.name}: {first_line(c.message) or c.outcome}" for c in bad[:limit]
    ]
    if len(bad) > limit:
        lines.append(f"... and {len(bad) - limit} more")
    return "\n".join(lines)


def _counts(cases: list[Case]) -> str:
    passed = sum(1 for c in cases if c.outcome == "passed")
    skipped = sum(1 for c in cases if c.outcome == "skipped")
    return f"{passed} passed, {len(_failures(cases))} failed, {skipped} skipped"


# 1. acceptance mapping -----------------------------------------------------------------------


def _at_marker(dec: ast.expr) -> str | None:
    """The id of a `pytest.mark.at("<id>")` decorator, else None."""
    if not (isinstance(dec, ast.Call) and len(dec.args) >= 1):
        return None
    f = dec.func
    if not (
        isinstance(f, ast.Attribute)
        and f.attr == "at"
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "mark"
        and isinstance(f.value.value, ast.Name)
        and f.value.value.id == "pytest"
    ):
        return None
    arg = dec.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _is_stub(fn: ast.FunctionDef | ast.AsyncFunctionDef, at_id: str) -> bool:
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "fail"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == f"{at_id} not implemented"
        ):
            return True
    return False


def _scan_ats(
    backend: Path,
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[str]]]:
    """(id -> [(module, function)] real, id -> [location] stubs) from collectable test files."""
    real: dict[str, list[tuple[str, str]]] = {}
    stubs: dict[str, list[str]] = {}
    for path in sorted((backend / "tests").rglob("*.py")):
        if not _is_test_file(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, ValueError, OSError):
            continue  # a broken test file surfaces in the `tests` check
        rel = path.relative_to(backend)
        module = ".".join(rel.with_suffix("").parts)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                at_id = _at_marker(dec)
                if at_id is None:
                    continue
                if _is_stub(node, at_id):
                    stubs.setdefault(at_id, []).append(f"{rel.as_posix()}::{node.name}")
                else:
                    real.setdefault(at_id, []).append((module, node.name))
    return real, stubs


def check_acceptance_mapping(
    solution: Solution, backend: Path, run: PytestRun | None = None
) -> CheckResult:
    real, stubs = _scan_ats(backend)
    wanted = [t.id for t in solution.acceptance_tests]
    missing = [i for i in wanted if i not in real and i not in stubs]
    stubbed = [i for i in wanted if i not in real and i in stubs]
    lines: list[str] = []
    if missing:
        lines.append("no test marked @pytest.mark.at for: " + ", ".join(missing))
    for i in stubbed:
        lines.append(f"{i}: still the generated stub ({', '.join(stubs[i])})")
    if run is not None:
        for at_id in wanted:
            if at_id not in real:
                continue
            found = [
                c
                for c in run.cases
                for module, func in real[at_id]
                if c.module == module and c.func == func
            ]
            if any(c.outcome == "passed" for c in found) and not _failures(found):
                continue
            if not found:
                why = "not collected or not executed by the test run"
            elif _failures(found):
                why = "failed: " + first_line(_failures(found)[0].message or "failed")
            else:
                why = "skipped: " + first_line(found[0].message or "no reason")
            lines.append(f"{at_id}: no passing executed test ({why})")
    if lines:
        return CheckResult("acceptance_mapping", "fail", "\n".join(lines))
    return CheckResult(
        "acceptance_mapping",
        "pass",
        f"{len(wanted)} acceptance tests mapped and passing",
    )


# 2-5. pytest results -----------------------------------------------------------------------------


def check_tests(run: PytestRun) -> CheckResult:
    if run.timed_out:
        return CheckResult("tests", "fail", f"pytest timed out after {TESTS_TIMEOUT}s")
    if not run.junit_ok:
        return CheckResult(
            "tests",
            "fail",
            f"pytest exited {run.returncode} without a result file\n{tail(run.output)}",
        )
    other_files = set(MATRIX_FILES.values())
    cases = [c for c in run.cases if c.file not in other_files]
    bad = _failures(cases)
    if bad:
        return CheckResult(
            "tests", "fail", f"{_counts(cases)}\n{_describe_failures(bad)}"
        )
    if "warnings summary" in run.output:
        return CheckResult(
            "tests",
            "fail",
            f"warnings in test run ({_counts(cases)})\n{tail(run.output)}",
        )
    if run.returncode != 0 and not _failures(run.cases):
        return CheckResult(
            "tests", "fail", f"pytest exited {run.returncode}\n{tail(run.output)}"
        )
    if not cases:
        return CheckResult("tests", "fail", "no tests collected")
    return CheckResult("tests", "pass", _counts(cases))


def check_matrix(name: str, run: PytestRun, expected: bool) -> CheckResult:
    if not expected:
        reason = {
            "permission_matrix": "no entities",
            "workflow_matrix": "no workflow transitions",
            "reports": "no reports",
        }[name]
        return CheckResult(name, "pass", reason)
    if run.timed_out:
        return CheckResult(name, "fail", "pytest timed out")
    if not run.junit_ok:
        return CheckResult(name, "fail", "pytest produced no result file")
    cases = [c for c in run.cases if c.file == MATRIX_FILES[name]]
    bad = _failures(cases)
    incomplete = [
        c
        for c in cases
        if c.outcome == "skipped" and c.message.startswith("sample-incomplete:")
    ]
    allowed = [
        c
        for c in cases
        if c.outcome == "skipped" and not c.message.startswith("sample-incomplete:")
    ]
    executed = sum(1 for c in cases if c.outcome == "passed")
    lines: list[str] = []
    if bad:
        lines.append("failures:\n" + _describe_failures(bad))
    if incomplete:
        lines.append(
            "sample-incomplete skips (the sample builder could not exercise these):\n"
            + _describe_failures(incomplete, 20)
        )
    if executed == 0 and not bad:
        lines.append("no case was executed")
    head = f"{executed} passed, {len(bad)} failed, {len(incomplete)} incomplete"
    if allowed:
        head += f", {len(allowed)} allowed skips"
        lines_allowed = _describe_failures(allowed, 20)
        if not lines:
            return CheckResult(
                name, "pass", head + "\nallowed skips:\n" + lines_allowed
            )
        lines.append("allowed skips:\n" + lines_allowed)
    if lines:
        return CheckResult(name, "fail", "\n".join([head, *lines]))
    return CheckResult(name, "pass", head)


# 6. static -------------------------------------------------------------------------------------


def check_static(solution_dir: Path, root: Path) -> CheckResult:
    app = solution_dir / "app"
    try:
        pack = load_status(solution_dir).pack
        policy = load_policy(root, pack)
    except Exception as exc:  # noqa: BLE001
        return CheckResult("static", "fail", f"cannot load policy: {exc}")
    anchor = read_anchor(root, solution_dir.name)
    issues = run_checks(app, policy, anchor)
    if issues:
        return CheckResult(
            "static", "fail", f"{len(issues)} issue(s)\n" + "\n".join(map(str, issues))
        )
    note = "" if anchor else " (no manifest anchor; regenerate to create it)"
    return CheckResult("static", "pass", "no issues" + note)


# 7. frontend build -----------------------------------------------------------------------------


def is_npm_network_failure(output: str) -> bool:
    """True only for npm's own network error codes (not 4xx/proxy/registry answers)."""
    return _NPM_NETWORK_CODE.search(output) is not None


def check_frontend_build(app: Path) -> CheckResult:
    npm = shutil.which("npm")
    if npm is None:
        return CheckResult("frontend_build", "skipped", "npm is not installed")
    src = app / "frontend"
    if not (src / "package.json").is_file():
        return CheckResult(
            "frontend_build", "fail", "app/frontend/package.json missing"
        )
    deadline = time.monotonic() + NPM_TIMEOUT
    with tempfile.TemporaryDirectory(prefix="asb-frontend-") as tmp:
        work = Path(tmp) / "frontend"
        try:
            shutil.copytree(
                src, work, ignore=shutil.ignore_patterns("node_modules", "dist")
            )
            inst = run_group(
                [npm, "install", "--no-audit", "--no-fund"],
                work,
                deadline - time.monotonic(),
                clean_env(),
            )
            if inst.returncode != 0:
                if is_npm_network_failure(inst.stdout):
                    return CheckResult(
                        "frontend_build",
                        "skipped",
                        "npm registry unreachable: " + first_line(tail(inst.stdout, 5)),
                    )
                return CheckResult(
                    "frontend_build", "fail", "npm install failed\n" + tail(inst.stdout)
                )
            build = run_group(
                [npm, "run", "build"], work, deadline - time.monotonic(), clean_env()
            )
            if build.returncode != 0:
                return CheckResult(
                    "frontend_build",
                    "fail",
                    "npm run build failed\n" + tail(build.stdout),
                )
            dist = work / "dist"
            if not (dist / "index.html").is_file():
                return CheckResult(
                    "frontend_build", "fail", "build produced no dist/index.html"
                )
            target = src / "dist"
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(dist, target)
        except subprocess.TimeoutExpired:
            return CheckResult(
                "frontend_build", "fail", f"timed out (limit {NPM_TIMEOUT}s in total)"
            )
        except OSError as exc:
            return CheckResult(
                "frontend_build", "fail", f"file or process error: {exc}"
            )
    return CheckResult("frontend_build", "pass", "built frontend/dist")


# entry point -------------------------------------------------------------------------------------


def _guard(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    """An unexpected exception becomes that check's failure; verify never crashes."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name, "fail", f"unexpected error: {type(exc).__name__}: {exc}"
        )


def verify(
    solution: Solution, solution_dir: Path, root: Path | None = None, **_: Any
) -> VerifyResult:
    solution_dir = Path(solution_dir)
    base = (
        Path(root)
        if root is not None
        else (
            solution_dir.parents[1] if len(solution_dir.parents) > 1 else solution_dir
        )
    )
    app = solution_dir / "app"
    backend = app / "backend"
    if not backend.is_dir():
        return VerifyResult(
            [
                CheckResult(
                    "acceptance_mapping", "fail", "no generated app; run asb build"
                )
            ]
        )
    try:
        run = run_pytest(backend)
    except Exception as exc:  # noqa: BLE001
        run = PytestRun(None, f"{type(exc).__name__}: {exc}", junit_ok=False)
    top = {e.name for e in solution.entities if not e.child_of}
    has_transitions = any(w.entity in top and w.transitions for w in solution.workflows)
    results = [
        _guard(
            "acceptance_mapping",
            lambda: check_acceptance_mapping(solution, backend, run),
        ),
        _guard("tests", lambda: check_tests(run)),
        _guard(
            "permission_matrix",
            lambda: check_matrix("permission_matrix", run, bool(top)),
        ),
        _guard(
            "workflow_matrix",
            lambda: check_matrix("workflow_matrix", run, has_transitions),
        ),
        _guard("reports", lambda: check_matrix("reports", run, bool(solution.reports))),
        _guard("static", lambda: check_static(solution_dir, base)),
    ]
    build = _guard("frontend_build", lambda: check_frontend_build(app))
    results.append(build)
    results.append(
        _guard("ui_smoke", lambda: check_ui_smoke(app, build.status == "pass"))
    )
    return VerifyResult(results)
