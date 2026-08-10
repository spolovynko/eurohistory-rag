"""Command-line entry points for the pipeline."""

import datetime as dt
import json
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from eurohistory_rag.core.config import Settings, get_settings
from eurohistory_rag.core.logging import configure_logging
from eurohistory_rag.eval import execute as execute_module
from eurohistory_rag.eval import gate as gate_module
from eurohistory_rag.eval import judge as judge_module
from eurohistory_rag.eval import probes as probes_module
from eurohistory_rag.eval import report as report_module
from eurohistory_rag.eval import split_probes as split_probes_module
from eurohistory_rag.eval import sweep as sweep_module
from eurohistory_rag.eval import synthetic as synthetic_module
from eurohistory_rag.eval import timeline as timeline_module
from eurohistory_rag.eval.metrics import summarise
from eurohistory_rag.eval.questions import (
    QUESTIONS_PATH,
    SUITE_TARGETS,
    counts,
    load_questions,
)
from eurohistory_rag.eval.record import (
    RUNS_DIR,
    RunMeta,
    read_records,
)
from eurohistory_rag.generation.client import OpenAIGenerator
from eurohistory_rag.pipeline.bronze import curate as curate_module
from eurohistory_rag.pipeline.bronze import ingest as ingest_module
from eurohistory_rag.pipeline.bronze.registry import (
    load_registry,
    write_registry,
)
from eurohistory_rag.pipeline.bronze.seeds import load_seeds
from eurohistory_rag.pipeline.bronze.wikipedia import (
    MAX_TITLES_PER_REQUEST,
    WikipediaClient,
)
from eurohistory_rag.pipeline.gold import build as gold_module
from eurohistory_rag.pipeline.gold.chunk import CHUNK_OVERLAP, CHUNK_SIZE
from eurohistory_rag.pipeline.index import build as index_module
from eurohistory_rag.pipeline.index.build import read_chunks
from eurohistory_rag.pipeline.silver import build as silver_module
from eurohistory_rag.retrieval.embedding import OpenAIEmbedder
from eurohistory_rag.retrieval.rerank import LocalReranker
from eurohistory_rag.retrieval.search import (
    DEFAULT_K,
)
from eurohistory_rag.retrieval.vectorstore import VectorStore

app = typer.Typer(help="eurohistory-rag pipeline commands.", no_args_is_help=True)

DEFAULT_SEEDS = Path("corpus/seeds.toml")
DEFAULT_REGISTRY = Path("corpus/registry.csv")
DEFAULT_BRONZE = Path("data/bronze")
DEFAULT_SILVER = Path("data/silver")
DEFAULT_GOLD = Path("data/gold")
DEFAULT_SYNTHETIC = Path("eval/synthetic.toml")


# The retrieval stack, built from settings in one place. Four commands need
# some of it now, and the three that need all of it must agree exactly: a
# reranker built one way in the eval and another way in the API is how Phase 8
# came to measure a pool the answer path never sees.
def _embedder(settings: Settings) -> OpenAIEmbedder:
    """The embedder every command shares."""
    return OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


def _store(settings: Settings) -> VectorStore:
    """A connection to the configured collection."""
    return VectorStore.connect(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_dimensions,
    )


def _reranker(settings: Settings) -> LocalReranker | None:
    """The reranker, or None when it is switched off."""
    return LocalReranker(settings.reranker_model) if settings.reranker_enabled else None


def _generator(settings: Settings, model: str) -> OpenAIGenerator:
    """A generation client for `model`, which may not be the answering model."""
    return OpenAIGenerator(
        api_key=settings.openai_api_key.get_secret_value(), model=model
    )


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
    payload_only: Annotated[
        bool,
        typer.Option(help="Rewrite metadata on existing points. Free, no embedding."),
    ] = False,
) -> None:
    """Embed data/gold/ into Qdrant.

    Drops and recreates the collection by default: chunk ids move whenever the
    chunk size changes, so writing into an old collection leaves points nothing
    will ever overwrite. Use --resume only to finish an interrupted run.

    This is the one command that costs money -- except with --payload-only,
    which updates metadata on points that already exist and touches no vector.
    Requires Qdrant running: `docker compose up -d`.
    """
    settings = get_settings()
    store = _store(settings)
    if payload_only:
        report = index_module.refresh_payloads(gold, store, batch_size)
        typer.echo(
            f"{report.indexed} payloads updated, {report.points} points "
            f"in {settings.qdrant_collection} -- $0.00, no vectors touched"
        )
        return

    embedder = _embedder(settings)
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
    # Only the hand-written sets are held to Phase 7's shape, and each suite is
    # checked separately: sixty questions in two batches of 8/8/8/6 add up to
    # 16/16/16/12, which is correct and would fail a check on the total. A
    # synthetic set is 150 questions of one kind by design, and warning about
    # that every run would train everyone to ignore the line.
    if questions_path == QUESTIONS_PATH:
        for suite in sorted({question.suite for question in questions}):
            want = SUITE_TARGETS.get(suite)
            have = counts([q for q in questions if q.suite == suite])
            if want is not None and have != want:
                typer.echo(f"note: {suite} is {have}, plan asks for {want}")

    settings = get_settings()
    # The whole run, including how the retrieval stack is wired, lives in
    # eval/execute.py. It is shared with the page's run button, and it is shared
    # precisely so a run started here and a run started there are the same run.
    # Built from settings and then narrowed, rather than field by field: a
    # field listed here by hand is a field the next one can be forgotten beside.
    config = replace(execute_module.RunConfig.from_settings(settings), k=k)
    directory = execute_module.execute(
        questions, settings, config, runs_dir=runs, note=note
    )

    summary = (directory / "summary.txt").read_text(encoding="utf-8")
    typer.echo(summary)
    typer.echo(f"\n{len(questions)} questions -> {directory}")


@app.command()
def synthesize(
    gold: Annotated[Path, typer.Option(help="Gold root.")] = DEFAULT_GOLD,
    out: Annotated[
        Path, typer.Option(help="Question file to write.")
    ] = DEFAULT_SYNTHETIC,
    count: Annotated[
        int, typer.Option(help="How many chunks to ask about.")
    ] = synthetic_module.DEFAULT_COUNT,
    seed: Annotated[
        int, typer.Option(help="Sampling seed; fixed so the set is reproducible.")
    ] = synthetic_module.SAMPLE_SEED,
) -> None:
    """Write a synthetic question set from Gold chunks.

    Costs money -- one small completion per chunk -- but needs no Qdrant: the
    questions come from the chunk file, not from search. Overwrites `out`, and
    doing so invalidates comparisons against runs made with the old set, so
    regenerate deliberately rather than casually.

    These questions are easier than the golden thirty and their scores are not
    comparable to them. They exist to notice a regression in the long tail.
    """
    settings = get_settings()
    chunks = synthetic_module.sample_chunks(read_chunks(gold), count, seed)
    typer.echo(f"{len(chunks)} chunks sampled, asking {settings.generation_model}...")

    report = synthetic_module.generate(
        chunks, _generator(settings, settings.generation_model)
    )
    path = synthetic_module.write(out, report.questions, settings.generation_model)
    typer.echo(
        f"{len(report.questions)} questions -> {path}  "
        f"({report.skipped} skipped by the model, {report.rejected} rejected by "
        f"the rules, {report.failed} failed)"
    )


@app.command()
def judge(
    run: Annotated[Path, typer.Argument(help="A run directory under eval/runs/.")],
) -> None:
    """Check every claim in a run's answers against the sources it was shown.

    Costs money and needs no Qdrant: it reads the run off disk. Writes
    `judgements.jsonl` and `faithfulness.txt` into the run directory and never
    touches `records.jsonl`, so a re-judge with a better prompt cannot damage
    the run it read.

    Run `judge-probe` first. An unvalidated judge produces a number nobody
    should act on.
    """
    settings = get_settings()
    records = read_records(run)
    judgements = judge_module.judge_all(
        records, _generator(settings, settings.judge_model)
    )

    summary = judge_module.summarise(judgements)
    report = judge_module.render(judgements, summary)
    judge_module.write(run, judgements)
    (run / "faithfulness.txt").write_text(report, encoding="utf-8")

    typer.echo(report)
    typer.echo(f"{len(judgements)} answers -> {run}")


@app.command("judge-probe")
def judge_probe(
    path: Annotated[
        Path, typer.Option("--probes", help="Probe file to run.")
    ] = probes_module.PROBES_PATH,
) -> None:
    """Put the faithfulness judge against claims whose verdict is already known.

    A few cents. Run it before trusting any faithfulness number and after any
    edit to the judge prompt -- Phase 7 shipped a metric that lied and Phase 8
    shipped a reranker that was broken, and both were the same failure: a
    component whose output looks plausible whether or not it works.
    """
    settings = get_settings()
    results = probes_module.run_probes(
        probes_module.load_probes(path), _generator(settings, settings.judge_model)
    )
    typer.echo(f"judge: {settings.judge_model}\n")
    typer.echo(probes_module.render(results))
    if not all(result.passed for result in results):
        raise typer.Exit(code=1)


@app.command("split-probe")
def split_probe(
    path: Annotated[
        Path, typer.Option("--probes", help="Split probe file to run.")
    ] = split_probes_module.SPLITS_PATH,
) -> None:
    """Put the claim splitter against answers whose correct split is written down.

    A few cents, and the other half of `judge-probe`. That command tests whether
    the judge reads a claim correctly; this one tests whether the claim it was
    given was ever the answer's claim. `stasi-scale` was reported unfaithful in
    three runs because it was not. D-102.
    """
    settings = get_settings()
    results = split_probes_module.run_split_probes(
        split_probes_module.load_split_probes(path),
        _generator(settings, settings.judge_model),
    )
    typer.echo(f"splitter: {settings.judge_model}\n")
    typer.echo(split_probes_module.render(results))
    if not all(result.passed for result in results):
        raise typer.Exit(code=1)


@app.command()
def sweep(
    questions_path: Annotated[
        Path, typer.Option("--questions", help="Question set to sweep.")
    ] = QUESTIONS_PATH,
    baseline: Annotated[
        Path | None,
        typer.Option(help="A run directory the control row must reproduce."),
    ] = None,
    configs: Annotated[
        str, typer.Option(help="Which set of arms to sweep: thinning or hybrid.")
    ] = "thinning",
) -> None:
    """Measure many retrieval settings at once, without generating anything.

    Costs one embedding per question and needs Qdrant. Retrieval is
    deterministic, so this is the cheap instrument: a dozen configurations for
    less than a single eval run.

    Pass `--baseline eval/runs/<id>` and the control row is checked against
    that run before the table is printed. Without it the table is unverified.
    """
    arms = {
        "thinning": sweep_module.THINNING_CONFIGS,
        "hybrid": sweep_module.HYBRID_CONFIGS,
    }
    if configs not in arms:
        raise typer.BadParameter(f"unknown config set {configs!r}")

    settings = get_settings()
    questions = [q for q in load_questions(questions_path) if q.expected]
    pools = sweep_module.collect_pools(
        questions, _embedder(settings), _store(settings), _reranker(settings)
    )
    rows = sweep_module.sweep(arms[configs], questions, pools)

    if baseline is not None:
        wanted = summarise([r for r in read_records(baseline) if r.expected_doc_ids])
        if sweep_module.control_matches(rows[0][1], wanted):
            typer.echo(f"control reproduces {baseline.name}\n")
        else:
            typer.echo(
                f"CONTROL FAILED: the harness does not reproduce {baseline.name}. "
                "The table below is not evidence of anything.\n"
            )

    typer.echo(sweep_module.render(rows))


@app.command()
def gate(
    baseline: Annotated[
        Path, typer.Argument(help="The run the candidate must not regress against.")
    ],
    candidate: Annotated[Path, typer.Argument(help="The new run.")],
    changed: Annotated[
        list[str] | None,
        typer.Option(help="A meta.json field this phase changed on purpose."),
    ] = None,
) -> None:
    """Compare two saved runs and exit non-zero if the candidate regressed.

    Free and offline: it reads both runs from disk and calls nothing. Run it at
    the end of a phase, after `evaluate`, and paste the output into the verdict.

    Anything the phase changed on purpose must be named -- `--changed reranker`
    -- and anything named must actually differ, which is how a run that measured
    nothing is caught. Retrieval, refusals and errors fail the gate; faithfulness
    is printed with its noise floor and never fails anything, because a quarter
    of that number's movement is the judge disagreeing with itself (D-088).
    """
    verdict = gate_module.gate(baseline, candidate, frozenset(changed or ()))
    typer.echo(gate_module.render(verdict, baseline.name, candidate.name))
    if not verdict.passed:
        raise typer.Exit(code=1)


@app.command()
def trace(
    run: Annotated[Path, typer.Argument(help="A run directory under eval/runs/.")],
    question: Annotated[
        str, typer.Option("--question", help="One question id, for its own timeline.")
    ] = "",
    replay: Annotated[
        bool, typer.Option(help="Ask that question again and diff the retrieval.")
    ] = False,
    answer: Annotated[
        bool, typer.Option(help="Also regenerate the answer. Costs about $0.002.")
    ] = False,
) -> None:
    """Where a run's time went, and optionally ask one of its questions again.

    Free and offline with no options: it reads spans already on disk, the same
    way `rescore` reads answers already on disk. `--replay` is the one form that
    touches the network -- one embedding call for the retrieval half, which
    rounds to nothing, plus one generation if `--answer` is given.

    Replaying uses the **recorded** standalone question rather than the typed
    one, so a follow-up is not silently rewritten a second time by a rewriter
    D-100 measured as non-deterministic. What it compares is retrieval: same
    question, same corpus, same twenty chunks, or something changed that nobody
    declared. D-101.
    """
    records = read_records(run)
    if not question:
        typer.echo(timeline_module.render_run(records))
        return

    chosen = next((r for r in records if r.question_id == question), None)
    if chosen is None:
        typer.echo(f"No question {question!r} in {run.name}.")
        raise typer.Exit(code=1)

    if not replay:
        typer.echo(timeline_module.render_one(chosen))
        return

    settings = get_settings()
    meta = RunMeta(**json.loads((run / "meta.json").read_text(encoding="utf-8")))
    # The run's own settings, not today's. Replaying a run under a different
    # reranker and reporting "retrieval changed" would be true and useless.
    config = replace(
        execute_module.RunConfig.from_settings(settings),
        k=meta.k,
        model=meta.generation_model,
        reranker=meta.reranker,
        hybrid=bool(meta.hybrid),
        temporal=bool(meta.temporal),
        conversation=bool(meta.conversation),
    )
    search, generation, _ = execute_module.build_stack(settings, config)
    typer.echo(
        timeline_module.render_replay(
            timeline_module.replay(
                chosen,
                search,
                generation if answer else None,
                depth=len(chosen.retrieved),
            )
        )
    )


@app.command()
def rescore(
    run: Annotated[Path, typer.Argument(help="A run directory under eval/runs/.")],
) -> None:
    """Recompute the summary and transcript of a run already on disk.

    Free, offline, and the reason records store raw observations rather than
    verdicts: fixing a metric should never cost another thirty model calls.
    The first baseline needed exactly this -- it reported no refusals because
    the phrase being matched had been guessed instead of read out of the prompt.

    The transcript is rewritten as well as the summary, which this command
    claimed to do and did not. A corrected summary sitting next to a stale
    transcript is worse than no rescore at all: the transcript is the file a
    person reads to check the number, and in Phase 23 it disagreed with the
    summary for exactly one question. D-097.
    """
    records = read_records(run)
    summary = report_module.render_by_suite(records)
    (run / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    meta = RunMeta(**json.loads((run / "meta.json").read_text(encoding="utf-8")))
    (run / "transcript.txt").write_text(
        report_module.render_transcript(meta, records) + "\n", encoding="utf-8"
    )
    typer.echo(summary)
