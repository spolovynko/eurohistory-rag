"""Making a run readable.

Two outputs, for two different jobs. The summary is the number you compare
between runs; the transcript is the thing you sit and read, because Phase 6
found two errors that no metric here would have caught.
"""

from collections.abc import Sequence

from eurohistory_rag.eval.metrics import (
    Summary,
    first_hit_rank,
    invalid_markers,
    refused,
    summarise_by_kind,
)
from eurohistory_rag.eval.record import EvalRecord, RunMeta


def _pct(value: float | None) -> str:
    """A rate as a percentage, or "n/a" where the metric does not apply."""
    return "n/a" if value is None else f"{value * 100:5.1f}%"


def _num(value: float | None) -> str:
    """A number to two decimals, or "n/a"."""
    return "n/a" if value is None else f"{value:5.2f}"


def render_summary(summaries: Sequence[Summary]) -> str:
    """The comparison table: one row per question kind, plus the total."""
    header = (
        f"{'kind':<13}{'n':>3}  {'r@5':>6} {'r@20':>6} {'cov@5':>6} {'MRR':>6} "
        f"{'top':>6} {'docs':>5} {'arts':>5} {'refuse':>7} "
        f"{'p50ms':>7} {'p95ms':>7} {'gen ms':>7}"
    )
    lines = [header, "-" * len(header)]
    for s in summaries:
        lines.append(
            f"{s.kind:<13}{s.questions:>3}  "
            f"{_pct(s.recall_at_5):>6} {_pct(s.recall_at_20):>6} "
            f"{_pct(s.coverage_at_5):>6} {_num(s.mrr):>6} "
            f"{s.mean_top_score:>6.3f} {s.mean_distinct_docs_at_5:>5.1f} "
            f"{s.mean_distinct_articles_at_5:>5.1f} {_pct(s.refusal_rate):>7} "
            f"{s.p50_total_ms:>7.0f} {s.p95_total_ms:>7.0f} {s.mean_generate_ms:>7.0f}"
        )

    total = summaries[-1] if summaries else None
    if total:
        lines += [
            "",
            f"no citation: {total.answers_with_no_citation}   "
            f"invalid marker: {total.answers_with_invalid_marker}   "
            f"errors: {total.errors}",
            f"tokens: {total.prompt_tokens or 0:,} prompt, "
            f"{total.completion_tokens or 0:,} completion",
        ]
    return "\n".join(lines)


def render_by_suite(records: Sequence[EvalRecord]) -> str:
    """One table per question batch, then one for everything together.

    The reason this exists is Phase 14: the corpus grew 81%, every headline
    number stayed identical, and the cause -- that all thirty questions
    described the old third of the corpus -- was visible only by reading the
    per-question table. A total that mixes two batches can only ever report
    their average. Reported separately, the golden thirty are a control that
    must reproduce the earlier baseline, and the new thirty are the measurement.
    """
    suites = sorted({record.suite for record in records})
    blocks = []
    for suite in suites:
        subset = [record for record in records if record.suite == suite]
        blocks.append(
            f"--- {suite} ({len(subset)} questions) "
            + "-" * max(0, 60 - len(suite))
            + "\n"
            + render_summary(summarise_by_kind(subset))
        )
    if len(suites) > 1:
        blocks.append(
            f"--- all suites ({len(records)} questions) "
            + "-" * 52
            + "\n"
            + render_summary(summarise_by_kind(list(records)))
        )
    return "\n\n".join(blocks)


def _verdict(record: EvalRecord) -> str:
    """A one-word retrieval verdict, or the reason there cannot be one."""
    if not record.expected_doc_ids:
        return "REFUSED" if refused(record) else "ANSWERED (expected refusal)"
    rank = first_hit_rank(record)
    if rank is None:
        return "MISS"
    return f"HIT at {rank}"


def render_transcript(meta: RunMeta, records: Sequence[EvalRecord]) -> str:
    """Every question, what came back, and what was answered.

    Marks the expected sections with `*` so a miss is visible at a glance,
    and prints the answer next to the chunks it cited -- the two things Phase 6
    proved have to be read side by side to catch a lost qualifier.
    """
    out = [
        f"# eval run {meta.run_id}",
        f"{meta.git_sha}  {meta.generation_model}  k={meta.k}  "
        f"collection={meta.collection} ({meta.points:,} points)",
    ]
    out.append(f"reranker: {meta.reranker or 'none'}")
    out.append(f"retrieval: {meta.hybrid or 'dense only'}")
    if meta.note:
        out.append(f"note: {meta.note}")

    for record in records:
        wanted = set(record.expected_doc_ids)
        out += [
            "",
            "=" * 78,
            f"[{record.question_id}] ({record.kind})  {_verdict(record)}",
            record.question,
            "",
            f"expected: {', '.join(record.expected_doc_ids) or '(nothing)'}",
            "",
            "retrieved:",
        ]
        for item in record.retrieved[:10]:
            mark = "*" if item.doc_id in wanted else " "
            sent = "<" if item.rank <= record.sources_sent else " "
            out.append(
                f" {mark}{sent} {item.rank:>2}. {item.score:.3f}  "
                f"{item.source[:56]:<56} {item.doc_id}"
            )

        cited = {c.number for c in record.citations}
        uncited = [n for n in range(1, record.sources_sent + 1) if n not in cited]
        out += [
            "",
            f"answer ({record.generation_model}):",
            record.answer or f"!! {record.error}",
            "",
            "cited: "
            + (
                ", ".join(f"[{c.number}] {c.source}" for c in record.citations)
                or "(none)"
            ),
            f"sent but not cited: {uncited or '(none)'}",
        ]
        if invalid_markers(record):
            out.append(f"INVALID MARKERS: {invalid_markers(record)}")
        out.append(
            f"timing: search {record.search_ms:.0f} ms, "
            f"generate {record.generate_ms:.0f} ms, total {record.total_ms:.0f} ms"
        )

        out.append("")
        out.append("--- what the model was shown " + "-" * 49)
        for item in record.retrieved[: record.sources_sent]:
            out += [f"[{item.rank}] {item.source}", item.text, ""]

    return "\n".join(out) + "\n"
