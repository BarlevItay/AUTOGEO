"""Typer CLI — all user-facing commands.

Commands land here as their pipeline stages are built; unimplemented commands
say so explicitly rather than pretending.
"""

from __future__ import annotations

from pathlib import Path

import typer

from autogeo import __version__
from autogeo.logging import setup_logging

app = typer.Typer(help="Automatic georeferencing of as-built PDFs/TIFFs.", no_args_is_help=True)
catalog_app = typer.Typer(help="Inspect and maintain per-jurisdiction control catalogs.")
app.add_typer(catalog_app, name="catalog")


@app.callback()
def _main(
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level."),
    log_format: str = typer.Option("console", "--log-format", help="console | json"),
) -> None:
    setup_logging(level=log_level, fmt=log_format)


@app.command()
def version() -> None:
    """Print the tool version."""
    typer.echo(f"autogeo {__version__}")


@app.command()
def run(
    pdf: Path = typer.Argument(..., exists=True, readable=True),
    page: int = typer.Option(0, "--page", help="Zero-based page number."),
    jurisdiction: str = typer.Option(None, "--jurisdiction", help="Jurisdiction id from config."),
    config: Path = typer.Option(None, "--config", help="YAML config path."),
    out: Path = typer.Option(Path("runs"), "--out", help="Output root directory."),
) -> None:
    """Georeference a single document (Phase 1)."""
    raise typer.Exit(typer.echo("not implemented yet: pipeline lands in Phase 1") or 2)


@catalog_app.command("show")
def catalog_show(jurisdiction: str = typer.Argument(...)) -> None:
    """Show the control-layer catalog for a jurisdiction (Phase 0)."""
    raise typer.Exit(typer.echo("not implemented yet: gis.catalog lands in Phase 0") or 2)


if __name__ == "__main__":
    app()
