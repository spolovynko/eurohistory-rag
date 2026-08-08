"""Reads saved eval runs off disk so something other than a text file can show them.

Nothing here runs an evaluation. `evaluate` costs money, needs Docker and takes
four minutes; a page that could trigger it from a browser would be a way to
spend $0.08 by clicking. This module only reads what is already on disk, which
makes every caller free and safe.

It is a separate module from `report.py` because that one formats for a
terminal. The two answer the same question in different shapes, and the shared
knowledge -- how a run is scored -- lives in `metrics.py`, which both call.
"""

from dataclasses import dataclass
from pathlib import Path

from eurohistory_rag.eval.gate import read_meta
from eurohistory_rag.eval.metrics import (
    Summary,
    first_hit_rank,
    hit_at,
    refused,
    summarise_by_kind,
)
from eurohistory_rag.eval.record import RUNS_DIR, EvalRecord, RunMeta, read_records

# A run directory holds these two; anything else on disk is not a run.
REQUIRED = ("meta.json", "records.jsonl")


@dataclass(frozen=True, slots=True)
class RunListing:
    """One run, reduced to what a picker needs to show."""

    run_id: str
    started_at: str
    questions: int
    points: int
    k: int
    reranker: str
    note: str


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    """What happened to one question, at the granularity a reader can scan.

    `first_hit_rank` is the interesting field and the reason this exists per
    question rather than only per kind: an average of 75% recall@5 does not say
    whether the misses were at rank 6 or rank 18, and those are different
    problems.
    """

    question_id: str
    kind: str
    suite: str
    scored: bool
    first_hit_rank: int | None
    hit_at_5: bool
    refused: bool
    total_ms: float


@dataclass(frozen=True, slots=True)
class RunView:
    """One run, scored the three ways this project reports it.

    `suites` is keyed "golden", "extended" and "all". Phase 15 kept the
    original thirty byte-identical precisely so they could be scored alone, and
    a view that only showed the combined number would throw that away.
    """

    meta: RunMeta
    suites: dict[str, list[Summary]]
    questions: list[QuestionOutcome]


def _is_run(directory: Path) -> bool:
    """Whether this directory is a run rather than a stray file."""
    return directory.is_dir() and all((directory / name).exists() for name in REQUIRED)


def list_runs(root: Path = RUNS_DIR) -> list[RunListing]:
    """Every run on disk, newest first.

    Newest first because a run directory is named for its timestamp, so sorting
    the names backwards is the same as sorting by date, and the run someone
    wants to look at is nearly always the last one.
    """
    if not root.is_dir():
        return []

    listings = []
    for directory in sorted(root.iterdir(), reverse=True):
        if not _is_run(directory):
            continue
        meta = read_meta(directory)
        listings.append(
            RunListing(
                run_id=meta.run_id,
                started_at=meta.started_at,
                questions=len(read_records(directory)),
                points=meta.points,
                k=meta.k,
                reranker=meta.reranker,
                note=meta.note,
            )
        )
    return listings


def _outcome(record: EvalRecord) -> QuestionOutcome:
    """One record as the row a reader scans."""
    scored = bool(record.expected_doc_ids)
    return QuestionOutcome(
        question_id=record.question_id,
        kind=record.kind,
        suite=record.suite,
        scored=scored,
        first_hit_rank=first_hit_rank(record) if scored else None,
        hit_at_5=hit_at(record, 5) if scored else False,
        refused=refused(record),
        total_ms=record.total_ms,
    )


def load_run(run_id: str, root: Path = RUNS_DIR) -> RunView | None:
    """One run, scored, or None if there is no such run.

    `run_id` arrives from a URL, so it is matched against the directories that
    actually exist rather than joined onto a path. A name is never trusted to
    stay inside the folder it is looked up in.
    """
    directory = (
        next((d for d in root.iterdir() if d.name == run_id), None)
        if root.is_dir()
        else None
    )
    if directory is None or not _is_run(directory):
        return None

    records = read_records(directory)
    suites = {"all": summarise_by_kind(records)}
    for suite in sorted({r.suite for r in records}):
        subset = [r for r in records if r.suite == suite]
        suites[suite] = summarise_by_kind(subset)

    return RunView(
        meta=read_meta(directory),
        suites=suites,
        questions=[_outcome(record) for record in records],
    )
