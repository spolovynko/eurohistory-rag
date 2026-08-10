"""Reading a recorded trace back: one query's tree, and a run's attribution.

Separate from `report.py` because it answers a different question. `report.py`
asks "was the answer any good"; this asks "where did the time go", and the two
change for different reasons -- a new metric is a change to one and not to the
other.

The number this module exists to produce is the **share of the wall clock each
stage owns**, and the number it exists to make visible is the one nobody
records: the part of `total_ms` that no span accounts for. D-101.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from eurohistory_rag.core.trace import Span, Trace
from eurohistory_rag.eval.record import EvalRecord
from eurohistory_rag.generation.service import GenerationService
from eurohistory_rag.retrieval.search import SearchService


@dataclass(frozen=True, slots=True)
class StageShare:
    """One stage across a whole run: how long it took and what share it owned.

    Both the median milliseconds and the median share, because they answer
    different questions. Milliseconds say what to go and fix; share says
    whether fixing it would be felt.
    """

    name: str
    depth: int
    questions: int
    median_ms: float
    median_share: float


def _top_level(spans: Sequence[Span]) -> list[Span]:
    """The spans that are slices of the wall clock rather than parts of another.

    Everything at depth 0. A child is already inside its parent, so adding
    `embed` to `search` would count the same milliseconds twice -- which is the
    mistake that makes a stage attribution add up to more than 100%.
    """
    return [span for span in spans if span.depth == 0]


def unattributed_ms(record: EvalRecord) -> float:
    """The part of this question's wall clock no stage claimed.

    The honesty check on the whole instrument. A trace that names six stages
    and accounts for 60% of the time is not a trace, it is six stages and a
    gap -- and the gap is where the next phase's finding lives.
    """
    return round(record.total_ms - sum(span.ms for span in _top_level(record.trace)), 1)


def stage_shares(records: Sequence[EvalRecord]) -> list[StageShare]:
    """Every stage seen across these records, with its median cost and share.

    Median rather than mean, for the reason latency is always reported that
    way: one question that waited nine seconds on a retried API call would move
    a mean and says nothing about what a reader experiences.

    A stage that ran on only some questions -- `rewrite`, which needs history --
    is scored over the questions it actually ran on, and `questions` says how
    many those were. Averaging it over questions that never ran it would report
    a rewriter that is four times cheaper than it is.
    """
    seen: dict[tuple[str, int], list[tuple[float, float]]] = {}
    for record in records:
        if record.total_ms <= 0:
            continue
        for span in record.trace:
            seen.setdefault((span.name, span.depth), []).append(
                (span.ms, span.ms / record.total_ms)
            )
    return [
        StageShare(
            name=name,
            depth=depth,
            questions=len(pairs),
            median_ms=round(median(ms for ms, _ in pairs), 1),
            median_share=round(median(share for _, share in pairs), 4),
        )
        for (name, depth), pairs in seen.items()
    ]


def render_one(record: EvalRecord) -> str:
    """One question's trace as a tree, deepest detail indented under its parent.

    Read top to bottom this is the order things happened; read by indentation it
    is what happened inside what. Both readings matter and one list gives them
    because a span is appended when it opens, not when it closes.
    """
    lines = [
        f"{record.question_id}  {record.question}",
        f"{'stage':<22} {'ms':>9} {'share':>7}  note",
        "-" * 78,
    ]
    for span in record.trace:
        share = span.ms / record.total_ms if record.total_ms else 0.0
        indent = "  " * span.depth
        lines.append(
            f"{indent + span.name:<22} {span.ms:>9.1f} {share:>6.1%}  {span.note}"
        )
    left = unattributed_ms(record)
    share = left / record.total_ms if record.total_ms else 0.0
    lines.append("-" * 78)
    lines.append(f"{'unattributed':<22} {left:>9.1f} {share:>6.1%}")
    lines.append(f"{'total':<22} {record.total_ms:>9.1f} {1.0:>6.1%}")
    return "\n".join(lines)


def render_run(records: Sequence[EvalRecord]) -> str:
    """Every stage across a run, ordered by the share of the clock it owns.

    Ordered by cost rather than by the order stages run in, because the
    question this table answers is "what should be looked at first" and the
    answer is the top row.
    """
    traced = [record for record in records if record.trace]
    if not traced:
        return "No question in this run carries a trace; it predates Phase 28."

    shares = sorted(stage_shares(traced), key=lambda s: s.median_share, reverse=True)
    lines = [
        f"{len(traced)} of {len(records)} questions traced",
        "",
        f"{'stage':<22} {'n':>4} {'median ms':>10} {'median share':>13}",
        "-" * 53,
    ]
    for stage in shares:
        indent = "  " * stage.depth
        lines.append(
            f"{indent + stage.name:<22} {stage.questions:>4} "
            f"{stage.median_ms:>10.1f} {stage.median_share:>12.1%}"
        )
    left = [unattributed_ms(record) / record.total_ms for record in traced]
    lines.append("-" * 53)
    lines.append(
        f"{'unattributed':<22} {len(traced):>4} {'':>10} {median(left):>12.1%}"
    )
    lines.append(
        f"{'total':<22} {len(traced):>4} "
        f"{median(r.total_ms for r in traced):>10.1f} {1.0:>12.1%}"
    )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Replay:
    """One recorded question, asked again, next to what was written down.

    The point is not that the answers match -- the model is not deterministic
    and never was. It is that the *retrieval* matches: same question, same
    corpus, same settings, same twenty chunks. A difference there means
    something changed that nobody declared, which is the failure D-089's gate
    exists to catch and this catches for one question in a second.
    """

    record: EvalRecord
    fresh: Trace
    recorded_chunks: list[str]
    fresh_chunks: list[str]
    answer: str = ""


def replay(
    record: EvalRecord,
    search: SearchService,
    generation: GenerationService | None = None,
    depth: int = 20,
) -> Replay:
    """Ask a recorded question again and trace it, from what the record says.

    **The recorded `standalone`, not the typed question.** A follow-up was
    rewritten before it was ever embedded, and the rewriter is not
    deterministic -- D-100 measured 2 of 13 rewrites differing between runs with
    no rewriter change. Replaying from the typed question would re-run the
    rewrite and compare two different searches while calling the difference a
    retrieval change.

    `generation` is optional and costs money when supplied: one answer, about
    two tenths of a cent. Retrieval alone is one embedding call, which rounds
    to nothing.
    """
    asked = record.standalone or record.question
    fresh = Trace()
    results = search.search(asked, k=depth, trace=fresh)
    answer = ""
    if generation is not None:
        answer = generation.answer_from(
            asked, results[: record.sources_sent], fresh
        ).text
    return Replay(
        record=record,
        fresh=fresh,
        recorded_chunks=[item.chunk_id for item in record.retrieved],
        fresh_chunks=[result.chunk_id for result in results],
        answer=answer,
    )


def render_replay(again: Replay) -> str:
    """The recorded trace, the fresh one, and every chunk that moved."""
    record = again.record
    lines = [
        f"{record.question_id}  {record.question}",
        f"asked as: {record.standalone or record.question}",
        "",
        "--- recorded " + "-" * 65,
        render_one(record) if record.trace else "(this run predates Phase 28)",
        "",
        "--- now " + "-" * 70,
        f"{'stage':<22} {'ms':>9}  note",
    ]
    lines += [
        f"{'  ' * span.depth + span.name:<22} {span.ms:>9.1f}  {span.note}"
        for span in again.fresh.spans
    ]

    recorded, found = again.recorded_chunks, again.fresh_chunks
    lines += ["", "--- retrieval " + "-" * 64]
    if recorded == found:
        lines.append(f"identical: all {len(recorded)} chunks, same order")
    else:
        lines.append(f"CHANGED: {len(set(recorded) ^ set(found))} chunks differ")
        for rank, (was, now) in enumerate(zip(recorded, found, strict=False), start=1):
            if was != now:
                lines.append(f"  rank {rank:>2}: {was}  ->  {now}")
    if again.answer:
        lines += ["", "--- answer " + "-" * 67, again.answer]
    return "\n".join(lines)
