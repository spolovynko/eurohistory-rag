"""Command-line entry points for the pipeline."""

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

from eurohistory_rag.core.config import get_settings
from eurohistory_rag.core.logging import configure_logging
from eurohistory_rag.pipeline.bronze import curate as curate_module
from eurohistory_rag.pipeline.bronze import ingest as ingest_module
from eurohistory_rag.pipeline.bronze.registry import (
    load_registry,
    load_seeds,
    write_registry,
)
from eurohistory_rag.pipeline.bronze.wikipedia import (
    MAX_TITLES_PER_REQUEST,
    WikipediaClient,
)

app = typer.Typer(help="eurohistory-rag pipeline commands.", no_args_is_help=True)

DEFAULT_SEEDS = Path("corpus/seeds.toml")
DEFAULT_REGISTRY = Path("corpus/registry.csv")
DEFAULT_BRONZE = Path("data/bronze")


@app.callback()
def main(
    verbose: Annotated[
        bool, typer.Option(help="Log at DEBUG instead of INFO.")
    ] = False,
) -> None:
    """eurohistory-rag pipeline commands."""
    configure_logging(verbose=verbose)


@app.command()
def curate(
    seeds: Annotated[Path, typer.Option(help="Seed list to read.")] = DEFAULT_SEEDS,
    out: Annotated[Path, typer.Option(help="Registry to write.")] = DEFAULT_REGISTRY,
    min_seeds: Annotated[
        int, typer.Option(help="Keep titles linked by at least this many seeds.")
    ] = curate_module.MIN_SEEDS,
) -> None:
    """Build the candidate title registry from the seed articles.

    Overwrites `out`. The result is a draft: review it by hand and commit it.
    """
    themes = load_seeds(seeds)
    with WikipediaClient(get_settings().wikipedia_user_agent) as client:
        entries = curate_module.curate(client, themes, min_seeds=min_seeds)
    write_registry(out, entries)
    typer.echo(f"{len(entries)} candidates from {len(themes)} themes -> {out}")


@app.command()
def ingest(
    registry: Annotated[
        Path, typer.Option(help="Reviewed registry to read.")
    ] = DEFAULT_REGISTRY,
    root: Annotated[Path, typer.Option(help="Bronze root.")] = DEFAULT_BRONZE,
    batch_size: Annotated[
        int, typer.Option(help="Titles per request.")
    ] = MAX_TITLES_PER_REQUEST,
    refresh: Annotated[
        bool, typer.Option(help="Refetch entries already in Bronze.")
    ] = False,
) -> None:
    """Fetch every registry entry into data/bronze/.

    Safe to re-run: already-stored entries are skipped unless --refresh.
    """
    entries = load_registry(registry)
    with WikipediaClient(get_settings().wikipedia_user_agent) as client:
        report = ingest_module.ingest(
            client,
            entries,
            root,
            fetched_at=dt.datetime.now(dt.UTC),
            batch_size=batch_size,
            refresh=refresh,
        )
    typer.echo(
        f"{report.written} written, {report.skipped} skipped, "
        f"{len(report.missing)} missing"
    )
    if report.missing:
        typer.echo("missing: " + ", ".join(sorted(report.missing)))
