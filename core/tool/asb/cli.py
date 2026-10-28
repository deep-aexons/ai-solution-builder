"""Typer entry point for the asb command."""

from pathlib import Path
from typing import Annotated

import typer

from asb import __version__
from asb.model import ModelError, load_solution
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
    issues = validate(solution)
    if issues:
        for issue in issues:
            typer.echo(str(issue))
        raise typer.Exit(1)
    typer.echo("OK: no issues")
