"""UI smoke check: run the built app in a throwaway copy and walk it with Playwright.

Only the Playwright driver runs in this process; the generated app (migrate, seed,
dev server) runs in subprocesses against a temporary SQLite database.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from asb.plugins import CheckResult

from .procutil import as_text, clean_env, first_line, kill_group, run_group, tail

UI_TIMEOUT = 300
UI_PASSWORD = "ui-smoke-pw-1"  # throwaway user in a throwaway database


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
    backend: Path, env: dict[str, str], *args: str, timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    return run_group([sys.executable, "manage.py", *args], backend, timeout, env)


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
                _drive_role(
                    browser, base, seed, role, username, notes, PwError, deadline
                )
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
    deadline: float,
) -> None:
    context = browser.new_context()
    page = context.new_page()

    def budget() -> None:
        """Per-step timeout that never exceeds what is left of the overall deadline."""
        left = deadline - time.monotonic()
        if left <= 0:
            raise UiFailure(f"role {role}, {step}: overall timeout reached")
        page.set_default_timeout(min(10_000, left * 1000))

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
        budget()
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
            budget()
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
            budget()
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
        raise UiFailure(f"role {role}, {step}: {first_line(str(exc))}{extra}") from exc
    finally:
        context.close()


def _fail(details: str) -> CheckResult:
    return CheckResult("ui_smoke", "fail", details)


def _setup_and_run(app: Path, tmp: Path, deadline: float, log: Path) -> CheckResult:
    def left() -> float:
        return deadline - time.monotonic()

    work = tmp / "app"
    try:
        shutil.copytree(
            app / "backend",
            work / "backend",
            ignore=shutil.ignore_patterns(
                "__pycache__", "db.sqlite3", "media", "staticfiles", ".pytest_cache"
            ),
        )
        shutil.copytree(app / "frontend" / "dist", work / "frontend" / "dist")
    except OSError as exc:
        return _fail(f"cannot copy the app for the smoke run: {exc}")
    backend = work / "backend"
    env = clean_env(DEBUG="1", DJANGO_SETTINGS_MODULE="config.settings")
    try:
        for args in (("migrate", "--noinput"), ("asb_sync_roles",)):
            proc = _manage(backend, env, *args, timeout=min(120, left()))
            if proc.returncode != 0:
                return _fail(
                    f"setup step manage.py {args[0]} failed\n" + tail(proc.stdout)
                )
        proc = _manage(
            backend,
            env,
            "shell",
            "-c",
            SEED_SCRIPT % {"password": UI_PASSWORD},
            timeout=min(120, left()),
        )
    except subprocess.TimeoutExpired as exc:
        return _fail(
            "setup timed out (ui_smoke overall limit "
            f"{UI_TIMEOUT}s)\n" + tail(as_text(exc.output))
        )
    except OSError as exc:
        return _fail(f"setup could not run: {exc}")
    line = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith("ASB-SEED ")), None
    )
    if proc.returncode != 0 or line is None:
        return _fail("seeding failed\n" + tail(proc.stdout))
    seed = json.loads(line.removeprefix("ASB-SEED "))
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with log.open("wb") as log_fh:
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
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            while True:
                if server.poll() is not None:
                    return _fail("dev server exited at start")
                if left() <= 0:
                    return _fail("dev server did not start before the deadline")
                try:
                    urllib.request.urlopen(base + "/api/auth/csrf/", timeout=2).close()
                    break
                except (urllib.error.URLError, OSError):
                    time.sleep(0.2)
            notes = _drive(base, seed, deadline)
        except UiFailure as exc:
            return _fail(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{type(exc).__name__}: {first_line(str(exc))}")
        finally:
            kill_group(server)
    details = f"{len(seed['users'])} role(s) walked; seeded {sorted(seed['seeded'])}"
    if seed["skipped"]:
        details += "\nnot seeded: " + "; ".join(
            f"{k} ({v})" for k, v in sorted(seed["skipped"].items())
        )
    return CheckResult("ui_smoke", "pass", details + "\n" + "\n".join(notes))


def check_ui_smoke(
    app: Path, frontend_ok: bool, timeout: float = UI_TIMEOUT
) -> CheckResult:
    if not frontend_ok:
        return CheckResult("ui_smoke", "skipped", "frontend_build did not pass")
    deadline = time.monotonic() + timeout
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return CheckResult("ui_smoke", "skipped", "python playwright is not installed")
    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "ui_smoke", "skipped", "no launchable chromium: " + first_line(str(exc))
        )
    with tempfile.TemporaryDirectory(prefix="asb-ui-") as tmp:
        log = Path(tmp) / "server.log"
        result = _setup_and_run(app, Path(tmp), deadline, log)
        if result.status == "fail" and log.is_file():
            text = tail(as_text(log.read_bytes()), 20)
            if text:
                result.details += "\ndev server log (tail):\n" + text
    return result
