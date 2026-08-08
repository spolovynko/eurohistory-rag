"""One evaluation, start to finish, for whoever asked for it.

This module exists because there are now two callers. `eurohistory evaluate`
types the knobs at a terminal; the page posts them from a browser. If each
built its own retrieval stack and wrote its own run directory, the two would
drift, and the first sign would be a comparison between a CLI run and a page
run that quietly measured two different systems -- which is Phase 8's dead
switch wearing a different coat.

So the wiring lives here once and both callers pass through it. The CLI keeps
its flags and its printing; the API keeps its job state and its progress. What
neither owns any more is *what an evaluation is*.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from eurohistory_rag.core.config import Settings
from eurohistory_rag.eval import report
from eurohistory_rag.eval import run as run_module
from eurohistory_rag.eval.questions import Question
from eurohistory_rag.eval.record import RUNS_DIR, new_run_id, write_run
from eurohistory_rag.generation.client import OpenAIGenerator
from eurohistory_rag.generation.service import GenerationService
from eurohistory_rag.retrieval.embedding import OpenAIEmbedder
from eurohistory_rag.retrieval.rerank import LocalReranker
from eurohistory_rag.retrieval.search import (
    DEFAULT_K,
    MAX_PER_DOCUMENT,
    OVERFETCH,
    RRF_K,
    SearchService,
)
from eurohistory_rag.retrieval.vectorstore import VectorStore

logger = logging.getLogger(__name__)

# The name of the file the prediction goes in. Named here rather than in the
# API because the rule belongs to the evaluation, not to the interface: any
# caller that starts a run is expected to have written one.
PREDICTION_FILE = "prediction.txt"


@dataclass(frozen=True, slots=True)
class RunConfig:
    """The four knobs a run can be started with.

    An empty `reranker` means reranking off, matching what `RunMeta` writes to
    disk -- so the thing chosen, the thing run and the thing recorded are all
    spelled the same way, and a comparison never has to translate between two
    vocabularies.
    """

    k: int
    model: str
    reranker: str
    hybrid: bool
    # No default, deliberately. This field was added with `= False` and the CLI,
    # which builds this object field by field, never passed it -- so a run made
    # with the flag on measured the flag off, and `meta.json` was the only thing
    # that said so. That is the Phase 8 A/A accident repeated inside the phase
    # that cites it. `VectorStore.upsert` made its sparse argument required for
    # this exact reason; this follows it. See the D-096 fourth addendum.
    temporal: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> "RunConfig":
        """What this process would run with nothing overridden."""
        return cls(
            k=DEFAULT_K,
            model=settings.generation_model,
            reranker=settings.reranker_model if settings.reranker_enabled else "",
            hybrid=settings.hybrid_enabled,
            temporal=settings.temporal_enabled,
        )


def build_stack(
    settings: Settings, config: RunConfig
) -> tuple[SearchService, GenerationService, VectorStore]:
    """The retrieval and answer path this run will use.

    Built fresh rather than borrowed from `api/dependencies.py`, and that is
    deliberate: a run started from the page must be the same object graph as one
    started from the terminal, and reusing the web process's cached services
    would make it the same only by inspection. The cost is one reranker load --
    a few seconds against a four-minute run -- and it buys the equality the
    whole phase is about.
    """
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
    search = SearchService(
        embedder,
        store,
        reranker=LocalReranker(config.reranker) if config.reranker else None,
        hybrid=config.hybrid,
        temporal=config.temporal,
    )
    generator = OpenAIGenerator(
        api_key=settings.openai_api_key.get_secret_value(), model=config.model
    )
    verifier = (
        OpenAIGenerator(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.verify_model,
        )
        if settings.verify_enabled
        else None
    )
    return search, GenerationService(search, generator, verifier=verifier), store


def execute(
    questions: Sequence[Question],
    settings: Settings,
    config: RunConfig,
    *,
    run_id: str | None = None,
    runs_dir: Path = RUNS_DIR,
    note: str = "",
    on_question: Callable[[int, Question], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    build: Callable[
        [Settings, RunConfig], tuple[SearchService, GenerationService, VectorStore]
    ] = build_stack,
) -> Path:
    """Ask every question, score it, and write the run directory.

    `run_id` is a parameter rather than something minted here because the caller
    may need the directory to exist *before* the first question -- which is
    exactly what the page does with `prediction.txt`. `write_run` creates the
    directory if it is not there and leaves anything already in it alone, so
    both orders work and neither can overwrite the other's files.

    `build` is the one seam: it is how the tests run this whole function without
    an OpenAI key or a Qdrant container, the same way `Depends` lets the API be
    tested against fakes. Every caller in the application leaves it alone.

    Raises `run.Cancelled` if `should_stop` says so, having written nothing.
    """
    search, generation, store = build(settings, config)

    records = run_module.run_all(
        questions,
        search,
        generation,
        answer_k=config.k,
        on_question=on_question,
        should_stop=should_stop,
    )
    meta = run_module.build_meta(
        run_id=run_id or new_run_id(),
        settings_collection=settings.qdrant_collection,
        embedding_model=settings.embedding_model,
        generation_model=config.model,
        points=store.count(),
        answer_k=config.k,
        max_per_document=MAX_PER_DOCUMENT,
        overfetch=OVERFETCH,
        reranker=config.reranker,
        hybrid=f"bm25+rrf(k={RRF_K})" if config.hybrid else "",
        temporal="year-overlap+rrf" if config.temporal else "",
        verifier=settings.verify_model if settings.verify_enabled else "",
        note=note,
    )

    directory = write_run(meta, records, runs_dir)
    (directory / "summary.txt").write_text(
        report.render_by_suite(records) + "\n", encoding="utf-8"
    )
    (directory / "transcript.txt").write_text(
        report.render_transcript(meta, records), encoding="utf-8"
    )
    return directory
