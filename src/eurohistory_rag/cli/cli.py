"""Command-line entry points for the pipeline."""

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

from eurohistory_rag.core.config import get_settings
from eurohistory_rag.core.logging import configure_logging
from eurohistory_rag.eval import report as report_module
from eurohistory_rag.eval import run as run_module
from eurohistory_rag.eval.metrics import summarise_by_kind
from eurohistory_rag.eval.questions import (
    QUESTIONS_PATH,
    TARGET_COUNTS,
    counts,
    load_questions,
)
from eurohistory_rag.eval.record import (
    RUNS_DIR,
    new_run_id,
    read_records,
    write_run,
)
from eurohistory_rag.generation.client import OpenAIGenerator
from eurohistory_rag.generation.service import GenerationService
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
from eurohistory_rag.pipeline.gold import build as gold_module
from eurohistory_rag.pipeline.gold.chunk import CHUNK_OVERLAP, CHUNK_SIZE
from eurohistory_rag.pipeline.index import build as index_module
from eurohistory_rag.pipeline.silver import build as silver_module
from eurohistory_rag.retrieval.embedding import OpenAIEmbedder
from eurohistory_rag.retrieval.search import (
    DEFAULT_K,
    MAX_PER_DOCUMENT,
    OVERFETCH,
    SearchService,
)
from eurohistory_rag.retrieval.vectorstore import VectorStore

app = typer.Typer(help="eurohistory-rag pipeline commands.", no_args_is_help=True)

DEFAULT_SEEDS = Path("corpus/seeds.toml")
DEFAULT_REGISTRY = Path("corpus/registry.csv")
DEFAULT_BRONZE = Path("data/bronze")
DEFAULT_SILVER = Path("data/silver")
DEFAULT_GOLD = Path("data/gold")


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


@app.command()
def silver(
    bronze: Annotated[Path, typer.Option(help="Bronze root.")] = DEFAULT_BRONZE,
    out: Annotated[Path, typer.Option(help="Silver root.")] = DEFAULT_SILVER,
) -> None:
    """Rebuild data/silver/ from data/bronze/.

    Always a full rebuild, and it overwrites: Silver is a cache, so there is
    nothing to resume and nothing to lose.
    """
    report = silver_module.build(bronze, out)
    typer.echo(
        f"{report.rows} rows from {report.articles - report.skipped} articles, "
        f"{report.skipped} skipped -> {report.path}"
    )


@app.command()
def chunk(
    silver_root: Annotated[
        Path, typer.Option("--silver", help="Silver root.")
    ] = DEFAULT_SILVER,
    out: Annotated[Path, typer.Option(help="Gold root.")] = DEFAULT_GOLD,
    size: Annotated[
        int, typer.Option(help="Characters of body per chunk.")
    ] = CHUNK_SIZE,
    overlap: Annotated[
        int, typer.Option(help="Characters carried from the previous chunk.")
    ] = CHUNK_OVERLAP,
) -> None:
    """Rebuild data/gold/ from data/silver/.

    Always a full rebuild, like `silver`. `--size` and `--overlap` default to
    the settled values and exist so Phase 7 can re-chunk from one command
    without editing code.
    """
    report = gold_module.build(silver_root, out, size, overlap)
    typer.echo(
        f"{report.chunks} chunks from {report.documents} documents -> {report.path}"
    )


@app.command()
def index(
    gold: Annotated[Path, typer.Option(help="Gold root.")] = DEFAULT_GOLD,
    batch_size: Annotated[
        int, typer.Option(help="Chunks per embedding request.")
    ] = index_module.DEFAULT_BATCH_SIZE,
    resume: Annotated[
        bool,
        typer.Option(help="Keep the collection and skip batches already stored."),
    ] = False,
) -> None:
    """Embed data/gold/ into Qdrant.

    Drops and recreates the collection by default: chunk ids move whenever the
    chunk size changes, so writing into an old collection leaves points nothing
    will ever overwrite. Use --resume only to finish an interrupted run.

    This is the one command that costs money. Requires Qdrant running:
    `docker compose up -d`.
    """
    settings = get_settings()
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    store = VectorStore.connect(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_dimensions,
    )
    report = index_module.build(gold, store, embedder, batch_size, resume=resume)
    typer.echo(
        f"{report.indexed} indexed, {report.skipped} skipped, "
        f"{report.points} points in {settings.qdrant_collection}"
    )


@app.command()
def evaluate(
    questions_path: Annotated[
        Path, typer.Option("--questions", help="Question set to run.")
    ] = QUESTIONS_PATH,
    runs: Annotated[Path, typer.Option(help="Where run directories go.")] = RUNS_DIR,
    k: Annotated[int, typer.Option(help="Sources shown to the model.")] = DEFAULT_K,
    note: Annotated[str, typer.Option(help="What is different about this run.")] = "",
) -> None:
    """Run every question through retrieval and generation, and score it.

    Costs money and needs Qdrant running. Writes one directory per run holding
    the raw records, the summary and a readable transcript -- nothing is ever
    overwritten, because comparing two runs is the entire point.
    """
    questions = load_questions(questions_path)
    have = counts(questions)
    if have != TARGET_COUNTS:
        typer.echo(f"note: question set is {have}, plan asks for {TARGET_COUNTS}")

    settings = get_settings()
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    store = VectorStore.connect(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_dimensions,
    )
    search = SearchService(embedder, store)
    generation = GenerationService(
        search,
        OpenAIGenerator(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.generation_model,
        ),
    )

    records = run_module.run_all(questions, search, generation, answer_k=k)
    meta = run_module.build_meta(
        run_id=new_run_id(),
        settings_collection=settings.qdrant_collection,
        embedding_model=settings.embedding_model,
        generation_model=settings.generation_model,
        points=store.count(),
        answer_k=k,
        max_per_document=MAX_PER_DOCUMENT,
        overfetch=OVERFETCH,
        note=note,
    )

    directory = write_run(meta, records, runs)
    summary = report_module.render_summary(summarise_by_kind(records))
    (directory / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    (directory / "transcript.txt").write_text(
        report_module.render_transcript(meta, records), encoding="utf-8"
    )

    typer.echo(summary)
    typer.echo(f"\n{len(records)} questions -> {directory}")


@app.command()
def rescore(
    run: Annotated[Path, typer.Argument(help="A run directory under eval/runs/.")],
) -> None:
    """Recompute the summary and transcript of a run already on disk.

    Free, offline, and the reason records store raw observations rather than
    verdicts: fixing a metric should never cost another thirty model calls.
    The first baseline needed exactly this -- it reported no refusals because
    the phrase being matched had been guessed instead of read out of the prompt.
    """
    records = read_records(run)
    summary = report_module.render_summary(summarise_by_kind(records))
    (run / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    typer.echo(summary)
