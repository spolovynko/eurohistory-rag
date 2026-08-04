"""Turning a run into numbers.

Every metric here is computed from records alone -- no model call, no network,
no judgement. That is the line: what a machine can count lives in this module,
and what only a person can decide stays out of it and goes in the scores file.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from statistics import mean

from eurohistory_rag.eval.record import EvalRecord

# The exact phrase prompt.md tells the model to open a refusal with. Matching on
# it is crude and it is the only automatic way to ask "did it refuse?" -- and it
# is coupled to the prompt: the first baseline reported 0% refusals because this
# constant was guessed rather than read, which is worth remembering before
# trusting any metric that was never checked against a real answer.
REFUSAL = "not in the sources"


def hit_at(record: EvalRecord, depth: int) -> bool:
    """Did any expected section appear in the top `depth` results?

    Any rather than all: a question is answerable if one good section came
    back, and demanding every listed section would punish a set where two of
    them say the same thing.
    """
    wanted = set(record.expected_doc_ids)
    return any(item.doc_id in wanted for item in record.retrieved[:depth])


def coverage_at(record: EvalRecord, depth: int) -> float:
    """What fraction of the expected sections appeared in the top `depth`.

    `hit_at` asks whether *any* expected section came back, which a comparison
    question passes by returning one side of the comparison and nothing of the
    other -- observed twice before this eval existed and confirmed by it. This
    is the number that notices: Versailles-vs-Trianon scores a hit and a third
    of the coverage, and only the second reads as the failure it is.
    """
    if not record.expected_doc_ids:
        return 0.0
    found = {item.doc_id for item in record.retrieved[:depth]}
    return sum(doc_id in found for doc_id in record.expected_doc_ids) / len(
        record.expected_doc_ids
    )


def first_hit_rank(record: EvalRecord) -> int | None:
    """The rank of the first expected section, or None if it never appeared."""
    wanted = set(record.expected_doc_ids)
    return next((item.rank for item in record.retrieved if item.doc_id in wanted), None)


def reciprocal_rank(record: EvalRecord) -> float:
    """1 divided by the rank of the first correct result; 0 if there was none.

    Recall answers "was it there at all", which treats rank 1 and rank 19 as
    the same success. This is the metric that notices the difference, and the
    difference is what a reranker exists to fix.
    """
    rank = first_hit_rank(record)
    return 1.0 / rank if rank else 0.0


def refused(record: EvalRecord) -> bool:
    """Did the answer decline to answer?"""
    return REFUSAL in record.answer.lower()


def invalid_markers(record: EvalRecord) -> list[int]:
    """Markers pointing at a source that was never sent.

    A [7] against six sources is the model inventing a citation. Rare, and the
    one citation failure that can be caught without reading anything.
    """
    return [n for n in record.markers_found if not 1 <= n <= record.sources_sent]


def distinct_documents(record: EvalRecord, depth: int) -> int:
    """How many different sections the top `depth` slots covered.

    Five slots holding two sections is five slots' worth of cost buying two
    viewpoints. Observed twice already, so it is counted rather than recalled.
    """
    return len({item.doc_id for item in record.retrieved[:depth]})


def distinct_articles(record: EvalRecord, depth: int) -> int:
    """How many different articles the top `depth` slots covered.

    The sharper version of the above, and the one that matters: thinning caps
    chunks per *section*, so five sections of the Versailles family pass it
    while contributing one article's worth of information.
    """
    return len({item.page_id for item in record.retrieved[:depth]})


@dataclass(frozen=True, slots=True)
class Summary:
    """One run reduced to the numbers worth comparing between runs."""

    kind: str
    questions: int
    recall_at_5: float | None
    recall_at_20: float | None
    coverage_at_5: float | None
    mrr: float | None
    mean_top_score: float
    mean_distinct_docs_at_5: float
    mean_distinct_articles_at_5: float
    refusal_rate: float
    answers_with_no_citation: int
    answers_with_invalid_marker: int
    p50_total_ms: float
    p95_total_ms: float
    mean_search_ms: float
    mean_generate_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    errors: int


def _percentile(values: Sequence[float], fraction: float) -> float:
    """The value at `fraction` through the sorted list, nearest-rank.

    Nearest-rank rather than interpolated: at thirty questions an interpolated
    p95 is a number invented between two real measurements, and a real one is
    easier to go and look at.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered)) - 1))
    return ordered[index]


def summarise(records: Collection[EvalRecord], kind: str = "all") -> Summary:
    """Reduce a set of records to one row.

    Recall and MRR are None when nothing in the set has an answer key -- the
    six unanswerable questions have none by design, and reporting 0.0 for them
    would read as a failure rather than as "not applicable".
    """
    scored = [r for r in records if r.expected_doc_ids]
    totals = [r.total_ms for r in records]
    prompts = [r.prompt_tokens for r in records if r.prompt_tokens is not None]
    completions = [
        r.completion_tokens for r in records if r.completion_tokens is not None
    ]

    return Summary(
        kind=kind,
        questions=len(records),
        recall_at_5=mean(hit_at(r, 5) for r in scored) if scored else None,
        recall_at_20=mean(hit_at(r, 20) for r in scored) if scored else None,
        coverage_at_5=mean(coverage_at(r, 5) for r in scored) if scored else None,
        mrr=mean(reciprocal_rank(r) for r in scored) if scored else None,
        mean_top_score=(
            mean(r.retrieved[0].score for r in records if r.retrieved)
            if any(r.retrieved for r in records)
            else 0.0
        ),
        mean_distinct_docs_at_5=(
            mean(distinct_documents(r, 5) for r in records) if records else 0.0
        ),
        mean_distinct_articles_at_5=(
            mean(distinct_articles(r, 5) for r in records) if records else 0.0
        ),
        refusal_rate=mean(refused(r) for r in records) if records else 0.0,
        answers_with_no_citation=sum(
            1 for r in records if not r.citations and not refused(r) and not r.error
        ),
        answers_with_invalid_marker=sum(1 for r in records if invalid_markers(r)),
        p50_total_ms=_percentile(totals, 0.50),
        p95_total_ms=_percentile(totals, 0.95),
        mean_search_ms=mean(r.search_ms for r in records) if records else 0.0,
        mean_generate_ms=mean(r.generate_ms for r in records) if records else 0.0,
        prompt_tokens=sum(prompts) if prompts else None,
        completion_tokens=sum(completions) if completions else None,
        errors=sum(1 for r in records if r.error),
    )


def summarise_by_kind(records: Sequence[EvalRecord]) -> list[Summary]:
    """One summary per question kind, plus one for the whole set.

    The overall number hides the interesting part: easy questions carry the
    average up while paraphrased ones carry it down, and a change that helps
    one and hurts the other looks like no change at all in the total.
    """
    kinds = sorted({r.kind for r in records})
    return [
        *(summarise([r for r in records if r.kind == kind], kind) for kind in kinds),
        summarise(records, "all"),
    ]
