"""Command-line entry points for the pipeline."""

import logging
from pathlib import Path
from typing import Annotated

import typer

from eurohistory_rag.core.config import get_settings
from eurohistory_rag.data_ingestion import curate as curate_module
from eurohistory_rag.data_ingestion.registry import load_seeds, write_registry
from eurohistory_rag.data_ingestion.wikipedia import WikipediaClient

app = typer.Typer(help="eurohistory-rag pipeline commands.", no_args_is_help=True)

DEFAULT_SEEDS = Path("corpus/seeds.toml")
DEFAULT_REGISTRY = Path("corpus/registry.csv")

@app.callback()
def main() -> None:
    """eurohistory-rag pipeline commands."""

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
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    themes = load_seeds(seeds)
    with WikipediaClient(get_settings().wikipedia_user_agent) as client:
        entries = curate_module.curate(client, themes, min_seeds=min_seeds)
    write_registry(out, entries)
    typer.echo(f"{len(entries)} candidates from {len(themes)} themes -> {out}")
