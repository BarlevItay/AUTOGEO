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


def _echo_layer_table(layers: list, proposed: bool = False) -> None:
    header = (
        f"{'tier':<4} {'level':<8} {'name':<44} {'geometry':<8} "
        f"{'acc_m':>6} {'source':<12} layer_key"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for layer in layers:
        acc = f"{layer.positional_accuracy_m:g}" if layer.positional_accuracy_m is not None else "-"
        source = f"PROPOSED({layer.score:g})" if proposed else layer.source
        typer.echo(
            f"{layer.doctrine_tier:<4} {layer.jurisdiction_level:<8} {layer.name[:44]:<44} "
            f"{layer.geometry_type:<8} {acc:>6} {source:<12} {layer.layer_key}"
        )


@catalog_app.command("show")
def catalog_show(
    jurisdiction: str = typer.Argument(...),
    era_year: int = typer.Option(None, "--era-year", help="Document era; reorders tiers."),
    config: Path = typer.Option(None, "--config", help="YAML config path."),
) -> None:
    """Show the ordered control-layer catalog for a jurisdiction."""
    from autogeo.config.loader import load_settings
    from autogeo.gis.catalog import Catalog

    settings = load_settings(config)
    try:
        catalog = Catalog(settings, jurisdiction)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    layers = catalog.layers_for(era_year, catalog.jurisdiction.state)
    typer.echo(f"{catalog.jurisdiction.display_name or jurisdiction} "
               f"(state={catalog.jurisdiction.state}, era_year={era_year or '-'}): "
               f"{len(layers)} layers")
    _echo_layer_table(layers)


@catalog_app.command("discover")
def catalog_discover(
    jurisdiction_or_url: str = typer.Argument(
        ..., help="Jurisdiction id from config (walks its rest_roots) or a REST root URL."
    ),
    save: Path = typer.Option(None, "--save", help="Persist proposals as JSON (list[ControlLayer])."),
    config: Path = typer.Option(None, "--config", help="YAML config path."),
) -> None:
    """Discover + doctrine-classify layers under ArcGIS REST roots.

    Output is PROPOSED control layers: assistant output for human review,
    never auto-trusted. Promote survivors into the curated registry by hand.
    """
    from autogeo.config.loader import load_settings
    from autogeo.gis.cache import make_cached_session
    from autogeo.gis.catalog import save_layers
    from autogeo.gis.discovery import discover
    from autogeo.gis.doctrine import classify_layers
    from autogeo.gis.rest_client import ArcGisClient

    settings = load_settings(config)
    if jurisdiction_or_url in settings.jurisdictions:
        roots = settings.jurisdictions[jurisdiction_or_url].rest_roots
        if not roots:
            typer.echo(f"error: jurisdiction {jurisdiction_or_url!r} has no rest_roots", err=True)
            raise typer.Exit(2)
    else:
        roots = [jurisdiction_or_url]

    client = ArcGisClient(settings.arcgis, session=make_cached_session(settings.cache))
    proposals = []
    for root in roots:
        typer.echo(f"discovering {root} ...")
        infos = discover(root, client, settings.arcgis.max_services)
        proposals.extend(classify_layers(infos, settings.doctrine))

    typer.echo(f"\n{len(proposals)} PROPOSED layers (review before trusting):")
    _echo_layer_table(proposals, proposed=True)
    if save is not None:
        save_layers(proposals, save)
        typer.echo(f"saved {len(proposals)} proposals to {save}")


if __name__ == "__main__":
    app()
