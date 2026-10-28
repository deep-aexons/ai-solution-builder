"""Typer entry point for the asb command."""

from pathlib import Path
from typing import Annotated

import typer

from asb import __version__
from asb.checks import load_policy, read_anchor, run_checks
from asb.connector import ConnectorError
from asb.discover import run_discovery
from asb.model import External, ModelError, Solution, load_solution
from asb.plugins import load_connector, load_pack
from asb.status import (
    APPROVAL_KINDS,
    STAGES,
    GateError,
    approve,
    clear_active,
    increment_verify_rounds,
    load_status,
    log_event,
    mark_done,
    mark_todo,
    new_solution,
    require,
    reset_verify,
    set_active,
    valid_name,
)
from asb.validate import validate
from asb.verify_report import passed, render_report

app = typer.Typer(
    name="asb",
    help="AI Solution Builder: generate and verify business modules.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"asb {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the asb version and exit.",
    ),
) -> None:
    """AI Solution Builder command-line tool."""


@app.command("validate")
def validate_cmd(
    solution_dir: Annotated[
        Path,
        typer.Argument(
            help="Solution folder (reads design/solution.yaml) or a solution file."
        ),
    ],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Project root containing packs/ (default: cwd)."),
    ] = None,
) -> None:
    """Validate a solution model before code generation."""
    path = (
        solution_dir
        if solution_dir.is_file()
        else solution_dir / "design" / "solution.yaml"
    )
    try:
        solution = load_solution(path)
    except ModelError as exc:
        for issue in exc.issues:
            typer.echo(issue)
        raise typer.Exit(1) from exc
    capabilities = None
    if solution_dir.is_dir() and (solution_dir / "status.json").exists():
        try:
            pack = load_pack(
                root if root is not None else Path.cwd(), load_status(solution_dir).pack
            )
        except (GateError, FileNotFoundError, ValueError, ImportError) as exc:
            typer.echo(f"error: {exc}")
            raise typer.Exit(1) from exc
        capabilities = pack.capabilities
    issues = validate(solution, capabilities)
    if issues:
        for issue in issues:
            typer.echo(str(issue))
        raise typer.Exit(1)
    typer.echo("OK: no issues")


RootOpt = Annotated[
    Path,
    typer.Option("--root", help="Project root containing solutions/ (default: cwd)."),
]


def _sol_dir(root: Path | None, name: str) -> Path:
    if not valid_name(name):
        typer.echo(f"error: invalid solution name '{name}'")
        raise typer.Exit(1)
    path = (root if root is not None else Path.cwd()) / "solutions" / name
    if not (path / "status.json").is_file():
        typer.echo(f"error: no solution '{name}' under {path.parent}")
        raise typer.Exit(1)
    return path


@app.command("new")
def new_cmd(
    name: Annotated[str, typer.Argument(help="Solution name (lowercase, hyphens).")],
    pack: Annotated[str, typer.Option("--pack", help="Target pack name.")],
    connector: Annotated[
        str | None, typer.Option("--connector", help="Connector name.")
    ] = None,
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Create a new client solution folder."""
    try:
        path = new_solution(
            root if root is not None else Path.cwd(), name, pack, connector
        )
    except (ValueError, FileExistsError) as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    typer.echo(f"created {path}")


@app.command("status")
def status_cmd(
    name: Annotated[str, typer.Argument(help="Solution name.")],
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Show stages, approvals and fix-loop rounds."""
    try:
        st = load_status(_sol_dir(root, name))
    except GateError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    typer.echo(f"solution: {st.solution}  pack: {st.pack}  connector: {st.connector}")
    typer.echo("stages:")
    for stage in STAGES:
        typer.echo(f"  {stage:<14}{st.stages.get(stage, 'todo')}")
    typer.echo("approvals:")
    if not st.approvals:
        typer.echo("  (none)")
    for a in st.approvals:
        extra = f"  v{a.model_version} {a.model_hash[:12]}" if a.model_hash else ""
        typer.echo(f"  {a.kind:<14}{a.by}  {a.at.isoformat()}{extra}")
    typer.echo(f"verify_rounds: {st.verify_rounds}")


@app.command("approve")
def approve_cmd(
    name: Annotated[str, typer.Argument(help="Solution name.")],
    kind: Annotated[str, typer.Argument(help=" | ".join(APPROVAL_KINDS))],
    by: Annotated[str, typer.Option("--by", help="Who approves.")],
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Record an approval."""
    try:
        approve(_sol_dir(root, name), kind, by)
    except (GateError, ValueError) as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    typer.echo(f"approved {kind} by {by}")


@app.command("gate")
def gate_cmd(
    name: Annotated[str, typer.Argument(help="Solution name.")],
    stage: Annotated[str, typer.Argument(help="Stage to check.")],
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Check whether a stage may start (exit 1 if refused)."""
    if stage not in STAGES:
        typer.echo(f"error: unknown stage '{stage}'")
        raise typer.Exit(1)
    try:
        require(_sol_dir(root, name), stage)
    except GateError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo("OK")


@app.command("check")
def check_cmd(
    name: Annotated[str, typer.Argument(help="Solution name.")],
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Run the static guardrail checks over the generated app (exit 1 on issues)."""
    sol_dir = _sol_dir(root, name)
    base = root if root is not None else Path.cwd()
    app_dir = sol_dir / "app"
    if not app_dir.is_dir():
        typer.echo(f"error: no app/ folder in {sol_dir}; build first")
        raise typer.Exit(1)
    try:
        policy = load_policy(base, load_status(sol_dir).pack)
    except (GateError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    anchor = read_anchor(base, name)
    if anchor is None:
        typer.echo(
            "warning: no manifest anchor (.asb/manifests); regenerate to create it"
        )
    issues = run_checks(app_dir, policy, anchor)
    log_event(sol_dir, "check", f"issues={len(issues)}")
    if issues:
        for issue in issues:
            typer.echo(str(issue))
        raise typer.Exit(1)
    typer.echo("OK: no issues")


@app.command("use")
def use_cmd(
    name: Annotated[str | None, typer.Argument(help="Solution to make active.")] = None,
    clear: Annotated[
        bool, typer.Option("--clear", help="Deactivate (no guardrails for the hook).")
    ] = False,
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Set or clear the active solution the PreToolUse hook confines the AI to."""
    base = root if root is not None else Path.cwd()
    if clear:
        clear_active(base)
        typer.echo("cleared active solution")
        return
    if name is None:
        typer.echo("error: give a solution name or --clear")
        raise typer.Exit(1)
    _sol_dir(root, name)
    set_active(base, name)
    typer.echo(f"active solution: {name}")


def _base(root: Path | None) -> Path:
    return root if root is not None else Path.cwd()


@app.command("build")
def build_cmd(
    name: Annotated[str, typer.Argument(help="Solution name.")],
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Generate the app from the approved design (stage 4)."""
    sol_dir = _sol_dir(root, name)
    base = _base(root)
    try:
        require(sol_dir, "build")
    except GateError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    try:
        solution = load_solution(sol_dir / "design" / "solution.yaml")
        pack = load_pack(base, load_status(sol_dir).pack)
    except ModelError as exc:
        for issue in exc.issues:
            typer.echo(issue)
        log_event(sol_dir, "build_failed", f"model issues={len(exc.issues)}")
        raise typer.Exit(1) from exc
    except (GateError, FileNotFoundError, ValueError, ImportError) as exc:
        typer.echo(f"error: {exc}")
        log_event(sol_dir, "build_failed", f"load error: {type(exc).__name__}")
        raise typer.Exit(1) from exc
    issues = validate(solution, pack.capabilities)
    if issues:
        for issue in issues:
            typer.echo(str(issue))
        log_event(sol_dir, "build_failed", f"validation issues={len(issues)}")
        raise typer.Exit(1)
    try:
        result = pack.generate(solution, sol_dir, root=base)
    except Exception as exc:
        typer.echo(f"error: build failed: {exc}")
        log_event(sol_dir, "build_failed", type(exc).__name__)
        raise typer.Exit(1) from exc
    mark_done(sol_dir, "build")
    reset_verify(sol_dir)
    set_active(base, name)
    log_event(
        sol_dir,
        "build",
        f"written={len(result.written)} skipped_ai_owned={len(result.skipped_ai_owned)}",
    )
    typer.echo(
        f"built {name}: {len(result.written)} generated file(s) written, "
        f"{len(result.skipped_ai_owned)} AI-owned file(s) kept"
    )


@app.command("verify")
def verify_cmd(
    name: Annotated[str, typer.Argument(help="Solution name.")],
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Run all automated evidence and write verify-report.md (stage 5)."""
    sol_dir = _sol_dir(root, name)
    base = _base(root)
    try:
        require(sol_dir, "verify")
    except GateError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    try:
        solution = load_solution(sol_dir / "design" / "solution.yaml")
        pack = load_pack(base, load_status(sol_dir).pack)
    except ModelError as exc:
        for issue in exc.issues:
            typer.echo(issue)
        log_event(sol_dir, "verify_failed", f"model issues={len(exc.issues)}")
        raise typer.Exit(1) from exc
    except (GateError, FileNotFoundError, ValueError, ImportError) as exc:
        typer.echo(f"error: {exc}")
        log_event(sol_dir, "verify_failed", f"load error: {type(exc).__name__}")
        raise typer.Exit(1) from exc
    round_no = increment_verify_rounds(sol_dir)
    try:
        result = pack.verify(solution, sol_dir, root=base)
    except Exception as exc:
        typer.echo(f"error: verify crashed: {exc}")
        log_event(sol_dir, "verify_failed", f"round={round_no} {type(exc).__name__}")
        mark_todo(sol_dir, "verify")
        raise typer.Exit(1) from exc
    (sol_dir / "verify-report.md").write_text(
        render_report(name, round_no, result), encoding="utf-8"
    )
    ok = passed(result)
    n_fail = sum(1 for c in result.checks if c.status == "fail")
    n_pass = sum(1 for c in result.checks if c.status == "pass")
    log_event(
        sol_dir,
        "verify",
        f"round={round_no} result={'pass' if ok else 'fail'} pass={n_pass} fail={n_fail}",
    )
    for c in result.checks:
        typer.echo(f"{c.name:<20}{c.status:<9}{(c.details.splitlines() or [''])[0]}")
    if ok:
        mark_done(sol_dir, "verify")
        typer.echo(f"PASS: see {sol_dir / 'verify-report.md'}")
        return
    mark_todo(sol_dir, "verify")  # a failed round never leaves a stale "done"
    typer.echo(f"FAIL: {n_fail} check(s) failed; see {sol_dir / 'verify-report.md'}")
    raise typer.Exit(1)


@app.command("discover")
def discover_cmd(
    name: Annotated[str, typer.Argument(help="Solution name.")],
    kind: Annotated[
        list[str] | None,
        typer.Option(
            "--kind",
            help="External kind to check (repeatable); used when no design exists yet.",
        ),
    ] = None,
    root: RootOpt = None,  # type: ignore[assignment]
) -> None:
    """Inspect the client's system and write discovery.md (stage 2)."""
    sol_dir = _sol_dir(root, name)
    base = _base(root)
    try:
        status = load_status(sol_dir)
    except GateError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    if status.connector is None:
        typer.echo(f"error: no connector configured for {name}")
        raise typer.Exit(1)
    model_path = sol_dir / "design" / "solution.yaml"
    if model_path.is_file():
        try:
            solution = load_solution(model_path)
        except ModelError as exc:
            for issue in exc.issues:
                typer.echo(issue)
            raise typer.Exit(1) from exc
    elif kind:
        solution = Solution.model_construct(
            solution=name,
            external=[External(name=k, kind=k, access="read") for k in kind],
        )
    else:
        typer.echo(
            "error: no design/solution.yaml yet; pass --kind <kind> "
            "(repeatable) to say which external data to check"
        )
        raise typer.Exit(1)
    connector = None
    error: Exception | None = None
    try:
        info = load_connector(base, status.connector)
        # Discovery never writes: no write operations are allowed.
        connector = info.module.from_env(allowed_writes=frozenset())
    except (FileNotFoundError, ValueError, ImportError) as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    except ConnectorError as exc:
        error = exc
    report = run_discovery(solution, connector, error)
    (sol_dir / "discovery.md").write_text(report.markdown, encoding="utf-8")
    log_event(
        sol_dir,
        "discover",
        f"connected={report.connected} gaps={report.gaps}",
    )
    if not report.connected:
        head = next(
            (
                ln
                for ln in report.markdown.splitlines()
                if ln.startswith("Connection failed")
            ),
            "Connection failed",
        )
        typer.echo(head)
        typer.echo(f"wrote {sol_dir / 'discovery.md'}; discovery not marked done")
        raise typer.Exit(1)
    mark_done(sol_dir, "discovery")
    typer.echo(f"wrote {sol_dir / 'discovery.md'}")
    if report.gaps:
        typer.echo(f"warning: {report.gaps} gap(s) found; see discovery.md")
