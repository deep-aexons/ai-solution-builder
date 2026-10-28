"""Typer entry point for the asb command."""

import typer

from asb import __version__

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
