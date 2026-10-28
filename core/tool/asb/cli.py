"""Typer entry point for the asb command."""

from pathlib import Path
from typing import Annotated

import typer

from asb import __version__
from asb.model import ModelError, load_solution
from asb.plugins import load_pack
from asb.status import (
    APPROVAL_KINDS,
    STAGES,
    GateError,
    approve,
    load_status,
    new_solution,
    require,
    valid_name,
)
from asb.validate import validate

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
