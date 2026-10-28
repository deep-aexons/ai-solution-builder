"""Stage 5 verifier: all automated evidence for a generated sidecar app.

The generated app is only ever run in subprocesses (pytest, manage.py, npm); the
only code run in this process is the Playwright driver for the UI smoke check.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asb.checks import load_policy, read_anchor, run_checks
from asb.model import Solution
from asb.plugins import CheckResult, VerifyResult
from asb.status import load_status

TESTS_TIMEOUT = 900
NPM_TIMEOUT = 600
UI_TIMEOUT = 300
MATRIX_FILES = {
    "permission_matrix": "test_permission_matrix",
    "workflow_matrix": "test_workflow_matrix",
    "reports": "test_reports_smoke",
}
_DROP_ENV = ("DEBUG", "SECRET_KEY", "DATABASE_URL", "DJANGO_SETTINGS_MODULE")
_NETWORK_ERRORS = re.compile(
    r"ENOTFOUND|ETIMEDOUT|ECONNREFUSED|ECONNRESET|EAI_AGAIN|EHOSTUNREACH|ENETUNREACH"
    r"|network|getaddrinfo|socket hang up|unable to resolve|proxy",
    re.IGNORECASE,
)
UI_PASSWORD = "ui-smoke-pw-1"  # throwaway user in a throwaway database


def _clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def _tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


# 1. acceptance mapping -----------------------------------------------------------


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


def check_acceptance_mapping(solution: Solution, backend: Path) -> CheckResult:
    real: dict[str, list[str]] = {}
    stubs: dict[str, list[str]] = {}
    for path in sorted((backend / "tests").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, ValueError, OSError):
            continue  # a broken test file surfaces in the `tests` check
        rel = path.relative_to(backend).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                at_id = _at_marker(dec)
                if at_id is None:
                    continue
                bucket = stubs if _is_stub(node, at_id) else real
                bucket.setdefault(at_id, []).append(f"{rel}::{node.name}")
    wanted = [t.id for t in solution.acceptance_tests]
    missing = [i for i in wanted if i not in real and i not in stubs]
    stubbed = [i for i in wanted if i not in real and i in stubs]
    if not missing and not stubbed:
        return CheckResult(
            "acceptance_mapping", "pass", f"{len(wanted)} acceptance tests mapped"
        )
    lines = []
    if missing:
        lines.append("no test marked @pytest.mark.at for: " + ", ".join(missing))
    for i in stubbed:
        lines.append(f"{i}: still the generated stub ({', '.join(stubs[i])})")
    return CheckResult("acceptance_mapping", "fail", "\n".join(lines))


# 2-5. pytest ------------------------------------------------------------------------


@dataclass
class Case:
    file: str
    name: str
    outcome: str  # passed | failed | error | skipped
    message: str = ""


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
        classname = tc.get("classname", "")
        module = next(
            (p for p in reversed(classname.split(".")) if p.startswith("test_")),
            classname,
        )
        outcome, message = "passed", ""
        for child in tc:
            if child.tag in ("failure", "error", "skipped"):
                outcome = "failed" if child.tag == "failure" else child.tag
                message = (child.get("message") or child.text or "").strip()
                break
        cases.append(Case(module, tc.get("name", ""), outcome, message))
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
            proc = subprocess.run(
                cmd,
                cwd=backend,
                env=_clean_env(),
                capture_output=True,
                text=True,
                timeout=TESTS_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout if isinstance(exc.stdout, str) else ""
            return PytestRun(None, out, timed_out=True)
        cases = _parse_junit(junit)
    return PytestRun(
        proc.returncode,
        proc.stdout + proc.stderr,
        cases or [],
        junit_ok=cases is not None,
    )


def _failures(cases: list[Case]) -> list[Case]:
    return [c for c in cases if c.outcome in ("failed", "error")]


def _describe_failures(bad: list[Case], limit: int = 10) -> str:
    lines = [
        f"{c.file}::{c.name}: {_first_line(c.message) or c.outcome}"
        for c in bad[:limit]
    ]
    if len(bad) > limit:
        lines.append(f"... and {len(bad) - limit} more")
    return "\n".join(lines)


def _counts(cases: list[Case]) -> str:
    n = {o: sum(1 for c in cases if c.outcome == o) for o in ("passed", "skipped")}
    bad = len(_failures(cases))
    return f"{n['passed']} passed, {bad} failed, {n['skipped']} skipped"


def check_tests(run: PytestRun) -> CheckResult:
    if run.timed_out:
        return CheckResult("tests", "fail", f"pytest timed out after {TESTS_TIMEOUT}s")
    other_files = set(MATRIX_FILES.values())
    cases = [c for c in run.cases if c.file not in other_files]
    bad = _failures(cases)
    if bad:
        return CheckResult(
            "tests", "fail", f"{_counts(cases)}\n{_describe_failures(bad)}"
        )
    if not run.junit_ok or (run.returncode not in (0, None) and not run.cases):
        return CheckResult(
            "tests",
            "fail",
            f"pytest exited {run.returncode} without a result file\n{_tail(run.output)}",
        )
    if "warnings summary" in run.output:
        return CheckResult(
            "tests",
            "fail",
            f"warnings in test run ({_counts(cases)})\n{_tail(run.output)}",
        )
    if run.returncode not in (0, 5) and not _failures(run.cases):
        return CheckResult(
            "tests",
            "fail",
            f"pytest exited {run.returncode}\n{_tail(run.output)}",
        )
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
        kinds = sorted({_first_line(c.message).split(":")[0] for c in allowed})
        head += f", {len(allowed)} allowed skips ({', '.join(kinds)})"
    if lines:
        return CheckResult(name, "fail", "\n".join([head, *lines]))
    return CheckResult(name, "pass", head)


# 6. static ---------------------------------------------------------------------------


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


# 7. frontend build ---------------------------------------------------------------------


def _run(
    cmd: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


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
        shutil.copytree(
            src, work, ignore=shutil.ignore_patterns("node_modules", "dist")
        )
        try:
            inst = _run(
                [npm, "install", "--no-audit", "--no-fund"],
                work,
                NPM_TIMEOUT,
            )
            if inst.returncode != 0:
                text = inst.stdout + inst.stderr
                if _NETWORK_ERRORS.search(text):
                    return CheckResult(
                        "frontend_build",
                        "skipped",
                        "npm registry unreachable: " + _first_line(_tail(text, 5)),
                    )
                return CheckResult(
                    "frontend_build", "fail", "npm install failed\n" + _tail(text)
                )
            build = _run(
                [npm, "run", "build"],
                work,
                max(30, int(deadline - time.monotonic())),
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                "frontend_build", "fail", f"timed out after {NPM_TIMEOUT}s"
            )
        if build.returncode != 0:
            return CheckResult(
                "frontend_build",
                "fail",
                "npm run build failed\n" + _tail(build.stdout + build.stderr),
            )
        dist = work / "dist"
        if not (dist / "index.html").is_file():
            return CheckResult(
                "frontend_build", "fail", "build produced no dist/index.html"
            )
        target = src / "dist"
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(dist, target)
    return CheckResult("frontend_build", "pass", "built frontend/dist")


# 8. UI smoke ------------------------------------------------------------------------------

SEED_SCRIPT = r'''
import datetime, json
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from workflow.definitions import ENTITIES, ROLE_NAMES, WORKFLOWS

PASSWORD = %(password)r
users = {}
for role in ROLE_NAMES:
    user, _ = get_user_model().objects.get_or_create(username="ui_" + role)
    user.set_password(PASSWORD)
    user.save()
    user.groups.set([Group.objects.get(name=role)])
    users[role] = user.get_username()

seeded, skipped = {}, {}


def minimal(entity, spec):
    """Attribute values for the required scalars; raises LookupError when impossible."""
    values = {}
    for f in spec["fields"]:
        if not f["required"] or f["type"] == "table":
            continue
        t, name = f["type"], f["name"]
        if t == "text":
            values[name] = "smoke"
        elif t == "number":
            values[name] = 1
        elif t in ("decimal", "money"):
            values[name] = "1"
        elif t == "date":
            values[name] = datetime.date(2024, 1, 2)
        elif t == "datetime":
            values[name] = timezone.now()
        elif t == "boolean":
            values[name] = False
        elif t == "choice":
            values[name] = f["options"][0]
        elif t == "external_ref":
            values[name + "_kind"] = f["to"][0]
            values[name + "_id"] = "SMOKE-1"
        elif t == "link":
            model = apps.get_model("entities", ENTITIES[f["to"][0]]["model"])
            target = model.objects.first()
            if target is None:
                raise LookupError("link target " + f["to"][0] + " not seeded")
            values[name] = target
        else:
            raise LookupError("required " + t + " field " + name + " is not seedable")
    return values


top = [n for n, s in ENTITIES.items() if not s["child_of"]]
pending = list(top)
for _ in range(len(top) + 1):
    still = []
    for name in pending:
        spec = ENTITIES[name]
        try:
            obj = apps.get_model("entities", spec["model"]).objects.create(**minimal(name, spec))
        except LookupError as exc:
            skipped[name] = str(exc)
            still.append(name)
        except Exception as exc:
            skipped[name] = type(exc).__name__ + ": " + str(exc)
        else:
            seeded[name] = obj.pk
            skipped.pop(name, None)
    pending = still
    if not pending:
        break
print("ASB-SEED " + json.dumps({"users": users, "seeded": seeded, "skipped": skipped}))
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _manage(
    backend: Path, env: dict[str, str], *args: str, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "manage.py", *args], backend, timeout, env)


class UiFailure(Exception):
    pass


def _drive(base: str, seed: dict[str, Any], deadline: float) -> list[str]:
    """Run the browser steps; returns notes. Raises UiFailure(step) on the first failure."""
    from playwright.sync_api import Error as PwError
    from playwright.sync_api import sync_playwright

    notes: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for role, username in seed["users"].items():
                if time.monotonic() > deadline:
                    raise UiFailure("overall timeout reached before role " + role)
                _drive_role(browser, base, seed, role, username, notes, PwError)
        finally:
            browser.close()
    return notes


def _drive_role(
    browser: Any,
    base: str,
    seed: dict[str, Any],
    role: str,
    username: str,
    notes: list[str],
    pw_error: type[Exception],
) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(10_000)
    problems: list[str] = []
    step = "start"

    def on_console(msg: Any) -> None:
        if msg.type != "error":
            return
        # Before login the app probes /api/meta/ and the browser logs its 401/403.
        probe = (
            step in ("start", "login")
            and "Failed to load resource" in msg.text
            and "/api/meta/" in (msg.location or {}).get("url", "")
            and re.search(r"\b40[13]\b", msg.text)
        )
        if not probe:
            problems.append(f"console error: {msg.text}")

    page.on("console", on_console)
    page.on("pageerror", lambda e: problems.append(f"uncaught exception: {e}"))

    def fail_if_problems() -> None:
        if problems:
            raise UiFailure(f"role {role}, {step}: {problems[0]}")

    try:
        step = "login"
        page.goto(base + "/")
        page.get_by_test_id("login-username").fill(username)
        page.get_by_test_id("login-password").fill(UI_PASSWORD)
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("whoami").wait_for()
        fail_if_problems()
        meta = page.evaluate("fetch('/api/meta/').then(r => r.json())")
        perms = meta["user"]["permissions"]
        roles = set(meta["user"]["roles"])
        workflows = {w["entity"]: w for w in meta["workflows"]}
        for entity in [e["name"] for e in meta["entities"] if not e["child_of"]]:
            have = perms.get(entity, [])
            if "read" not in have:
                continue
            step = f"open list {entity}"
            page.get_by_test_id("nav-" + entity).click()
            page.get_by_test_id("list-" + entity).wait_for()
            page.get_by_test_id("list-table").wait_for()
            fail_if_problems()
            if "create" in have:
                step = f"open new form {entity}"
                page.get_by_test_id("list-new").click()
                page.locator('[data-testid^="field-"]').first.wait_for()
                fail_if_problems()
                page.get_by_test_id("nav-" + entity).click()
                page.get_by_test_id("list-table").wait_for()
            pk = seed["seeded"].get(entity)
            if pk is None:
                continue
            step = f"open record {entity} #{pk}"
            page.get_by_test_id(f"open-{pk}").click()
            page.get_by_test_id("form-" + entity).wait_for()
            fail_if_problems()
            wf = workflows.get(entity)
            if wf is not None:
                state = page.get_by_test_id("state").inner_text().strip()
                raw_state = wf["initial"]  # seeded records start in the initial state
                expected = sorted(
                    {
                        t["action"]
                        for t in wf["transitions"]
                        if t["from"] == raw_state
                        and roles & set(t["roles"])
                        and (t["from"] == wf["initial"] or "approve" in have)
                    }
                )
                for action in expected:
                    step = f"action button {action} on {entity} (state {state})"
                    page.get_by_test_id("action-" + action).wait_for()
                notes.append(f"{role}/{entity}: actions {expected or 'none'}")
        for report in meta["reports"]:
            step = f"open report {report}"
            page.get_by_test_id("nav-report-" + report).click()
            page.get_by_test_id("report-" + report).wait_for()
            with page.expect_response(
                lambda r, n=report: f"/api/reports/{n}/" in r.url
            ) as info:
                page.get_by_test_id("report-run").click()
            if info.value.status != 200:
                raise UiFailure(
                    f"role {role}, {step}: report API answered {info.value.status}"
                )
            page.wait_for_timeout(200)
            fail_if_problems()
        step = "finish"
        fail_if_problems()
    except UiFailure:
        raise
    except pw_error as exc:
        extra = f" ({problems[0]})" if problems else ""
        raise UiFailure(f"role {role}, {step}: {_first_line(str(exc))}{extra}") from exc
    finally:
        context.close()


def check_ui_smoke(app: Path, frontend_ok: bool) -> CheckResult:
    if not frontend_ok:
        return CheckResult("ui_smoke", "skipped", "frontend_build did not pass")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return CheckResult("ui_smoke", "skipped", "python playwright is not installed")
    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "ui_smoke",
            "skipped",
            "no launchable chromium: " + _first_line(str(exc)),
        )
    deadline = time.monotonic() + UI_TIMEOUT
    with tempfile.TemporaryDirectory(prefix="asb-ui-") as tmp:
        work = Path(tmp) / "app"
        shutil.copytree(
            app / "backend",
            work / "backend",
            ignore=shutil.ignore_patterns(
                "__pycache__", "db.sqlite3", "media", "staticfiles", ".pytest_cache"
            ),
        )
        shutil.copytree(app / "frontend" / "dist", work / "frontend" / "dist")
        backend = work / "backend"
        env = _clean_env(DEBUG="1", DJANGO_SETTINGS_MODULE="config.settings")
        for args in (("migrate", "--noinput"), ("asb_sync_roles",)):
            proc = _manage(backend, env, *args)
            if proc.returncode != 0:
                return CheckResult(
                    "ui_smoke",
                    "fail",
                    f"setup step manage.py {args[0]} failed\n"
                    + _tail(proc.stdout + proc.stderr),
                )
        proc = _manage(
            backend, env, "shell", "-c", SEED_SCRIPT % {"password": UI_PASSWORD}
        )
        line = next(
            (ln for ln in proc.stdout.splitlines() if ln.startswith("ASB-SEED ")), None
        )
        if proc.returncode != 0 or line is None:
            return CheckResult(
                "ui_smoke",
                "fail",
                "seeding failed\n" + _tail(proc.stdout + proc.stderr),
            )
        seed = json.loads(line.removeprefix("ASB-SEED "))
        port = _free_port()
        server = subprocess.Popen(
            [
                sys.executable,
                "manage.py",
                "runserver",
                f"127.0.0.1:{port}",
                "--noreload",
            ],
            cwd=backend,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(150):
                if server.poll() is not None:
                    return CheckResult("ui_smoke", "fail", "dev server exited at start")
                try:
                    urllib.request.urlopen(base + "/api/auth/csrf/", timeout=2).close()
                    break
                except (urllib.error.URLError, OSError):
                    time.sleep(0.2)
            else:
                return CheckResult("ui_smoke", "fail", "dev server did not start")
            notes = _drive(base, seed, deadline)
        except UiFailure as exc:
            return CheckResult("ui_smoke", "fail", str(exc))
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                "ui_smoke", "fail", f"{type(exc).__name__}: {_first_line(str(exc))}"
            )
        finally:
            try:
                os.killpg(server.pid, signal.SIGTERM)
                server.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(server.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    details = f"{len(seed['users'])} role(s) walked; seeded {sorted(seed['seeded'])}"
    if seed["skipped"]:
        details += "\nnot seeded: " + "; ".join(
            f"{k} ({v})" for k, v in sorted(seed["skipped"].items())
        )
    return CheckResult("ui_smoke", "pass", details + "\n" + "\n".join(notes))


# entry point -----------------------------------------------------------------------------


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
    results = [check_acceptance_mapping(solution, backend)]
    run = run_pytest(backend)
    results.append(check_tests(run))
    top = {e.name for e in solution.entities if not e.child_of}
    has_transitions = any(w.entity in top and w.transitions for w in solution.workflows)
    results.append(check_matrix("permission_matrix", run, bool(top)))
    results.append(check_matrix("workflow_matrix", run, has_transitions))
    results.append(check_matrix("reports", run, bool(solution.reports)))
    results.append(check_static(solution_dir, base))
    build = check_frontend_build(app)
    results.append(build)
    results.append(check_ui_smoke(app, build.status == "pass"))
    return VerifyResult(results)
