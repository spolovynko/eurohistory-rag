"""Starting an evaluation from the page, with everything that must happen first.

The endpoint in `main.py` does HTTP: it reads a request, refuses the bad ones,
returns a status. This module holds the rest -- what has to be true before a
run is worth starting, what the run is compared against, and the work the
background thread actually does.

Kept apart from `main.py` because none of it is about HTTP, and kept out of
`eval/` because it is about a button: the CLI has a person in front of it who
can read an error and try again, and this has a dialog that has to say what is
wrong before four minutes and eight cents are spent.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from eurohistory_rag.api.jobs import EvalJob
from eurohistory_rag.core.config import Settings
from eurohistory_rag.eval import gate as gate_module
from eurohistory_rag.eval.execute import PREDICTION_FILE, RunConfig, execute
from eurohistory_rag.eval.questions import Question
from eurohistory_rag.eval.record import RUNS_DIR
from eurohistory_rag.retrieval.search import RRF_K
from eurohistory_rag.retrieval.vectorstore import VectorStore, VectorStoreUnavailable

logger = logging.getLogger(__name__)

# The meta.json fields a knob can move. The gate takes these names on
# `--changed`, so the page declaring a change and a person typing one produce
# the identical argument -- which is the point of deriving it rather than
# asking for it.
DECLARABLE = ("generation_model", "k", "reranker", "hybrid")


@dataclass(frozen=True, slots=True)
class Precondition:
    """One thing that must be true, and what to do when it is not."""

    name: str
    ok: bool
    detail: str


def check_preconditions(settings: Settings) -> list[Precondition]:
    """Everything that would make a run fail, checked before it starts.

    The failure this prevents is the expensive one: Qdrant down is discovered on
    question one, but a collection that is up and *empty* answers sixty
    questions with nothing and produces a run that looks real and scores zero.
    Both cost the same four minutes; only one is obvious afterwards.
    """
    checks = [
        Precondition(
            name="api key",
            ok=bool(settings.openai_api_key.get_secret_value()),
            detail="OPENAI_API_KEY is set in .env",
        )
    ]
    try:
        store = VectorStore.connect(
            settings.qdrant_url,
            settings.qdrant_collection,
            settings.embedding_dimensions,
        )
        ready = store.is_ready()
        points = store.count() if ready else 0
    except (VectorStoreUnavailable, OSError) as failure:
        logger.warning("precondition check could not reach the store: %s", failure)
        ready, points = False, 0

    checks.append(
        Precondition(
            name="vector store",
            ok=ready,
            detail=(
                f"{settings.qdrant_url} is answering"
                if ready
                else f"{settings.qdrant_url} is unreachable — start it with "
                "`docker compose up -d`"
            ),
        )
    )
    checks.append(
        Precondition(
            name="indexed corpus",
            ok=points > 0,
            detail=(
                f"{points:,} points in '{settings.qdrant_collection}'"
                if points
                else f"'{settings.qdrant_collection}' is empty — run "
                "`eurohistory index`"
            ),
        )
    )
    return checks


def changed_fields(baseline: Path, config: RunConfig) -> frozenset[str]:
    """Which knobs this run moves relative to the run it will be gated against.

    Derived rather than typed. The gate refuses a comparison whose declared
    change did not happen, which is Phase 8's dead switch turned into a check --
    and a check nobody has to remember to write is a check that runs.
    """
    try:
        meta = gate_module.read_meta(baseline)
    except (OSError, ValueError):
        return frozenset()

    mine = {
        "generation_model": config.model,
        "k": config.k,
        "reranker": config.reranker,
        "hybrid": f"bm25+rrf(k={RRF_K})" if config.hybrid else "",
    }
    return frozenset(
        name
        for name in DECLARABLE
        # `hybrid` is a description on disk and a boolean here, so both sides are
        # compared as the string meta.json holds. Anything else would report a
        # change every time.
        if str(getattr(meta, name)) != str(mine[name])
    )


def write_prediction(run_id: str, prediction: str, runs_dir: Path = RUNS_DIR) -> Path:
    """Create the run directory and put the prediction in it. Nothing else.

    This is the whole of obligation 9 as code. It runs inside the request that
    started the run, before any thread exists and therefore before any question
    is asked, so there is no ordering in which a number arrives first and the
    prediction is written to fit it.
    """
    directory = runs_dir / run_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / PREDICTION_FILE).write_text(
        prediction.strip() + "\n", encoding="utf-8"
    )
    return directory


def make_work(
    questions: Sequence[Question],
    settings: Settings,
    config: RunConfig,
    *,
    run_id: str,
    note: str,
    baseline: Path | None,
    runs_dir: Path = RUNS_DIR,
) -> Callable[[EvalJob], str]:
    """The function the background thread runs: the eval, then the gate.

    The gate is here rather than left to the person who clicked because a run
    without its comparison is half a result -- and the half that gets skipped.
    A gate failure is not a job failure: the run happened, it cost money, and
    its verdict is a finding rather than an error.
    """

    def work(job: EvalJob) -> str:
        directory = execute(
            questions,
            settings,
            config,
            run_id=run_id,
            runs_dir=runs_dir,
            note=note,
            on_question=lambda position, question: job.progress(position, question.id),
            should_stop=lambda: job.stopping,
        )
        if baseline is not None:
            declared = changed_fields(baseline, config)
            verdict = gate_module.gate(baseline, directory, declared)
            job.annotate(
                baseline=baseline.name,
                gate_report=gate_module.render(verdict, baseline.name, directory.name),
                gate_passed=verdict.passed,
            )
        return str(directory)

    return work
