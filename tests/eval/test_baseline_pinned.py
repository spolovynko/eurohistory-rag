"""The published numbers, asserted against the run they were published from.

Every table in `decisions.md` from Phase 15 onward quotes these figures, and
until now nothing in the repository connected them to the records they were
computed from. A metric edited in good faith would move all of them silently --
which is exactly what happened: `metrics.REFUSAL` matched only one of the two
phrases the prompt uses to decline, and fixing it in Phase 27 changed a number
published across many runs. This file is why that was a deliberate re-pin with
both values written down rather than a silent drift. D-102.

It is also the only part of the eval that can run in CI. Producing a run needs
Qdrant, 54,903 points and a paid key; **re-scoring** one needs a text file that
is already in git, so the scoring code is held to its published output on every
commit, for free.
"""

from pathlib import Path

import pytest

from eurohistory_rag.eval.metrics import Summary, refused, summarise
from eurohistory_rag.eval.record import EvalRecord, read_records

# The Phase 15 baseline: sixty questions, nine themes, 54,903 points. Chosen as
# the pin because it is the run every current published figure comes from and it
# is the run Phase 16 measured the noise floor against.
BASELINE = Path(__file__).parents[2] / "eval" / "runs" / "2026-08-06T1703Z"

# recall@5, recall@20, coverage@5, MRR, top-1 score -- to three decimals, which
# is the precision the tables print. The fourth decimal of top-1 is embedding
# API noise and pinning it would fail a build on nothing.
#
# **The refusal column was re-pinned in Phase 27 and the old values are kept
# here.** It read `golden 2, extended 5, all 7` under the one-phrase rule, and
# reads `2, 6, 8` now. The one answer that moved is `seveso-1976`, in the
# extended suite: it declines the whole question in the wording the old rule
# could not see. Every other figure in this table is byte-identical before and
# after, which is the evidence that the fix touched the refusal test and nothing
# else. D-102.
PUBLISHED = {
    "golden": (30, 0.750, 1.000, 0.479, 0.536, 0.655, 2),
    "extended": (30, 0.625, 0.917, 0.389, 0.453, 0.592, 6),
    "all": (60, 0.688, 0.958, 0.434, 0.494, 0.624, 8),
}


def _subset(suite: str) -> list[EvalRecord]:
    """The records of one suite, or all sixty."""
    records = read_records(BASELINE)
    if suite == "all":
        return records
    return [record for record in records if record.suite == suite]


def _round(value: float | None) -> float:
    """Three decimals, the precision the published tables use."""
    assert value is not None
    return round(value, 3)


@pytest.mark.parametrize("suite", sorted(PUBLISHED))
def test_the_baseline_still_scores_what_was_published(suite: str) -> None:
    """Today's metrics code must reproduce the numbers in decisions.md.

    A failure here does not mean the system regressed -- the records are frozen.
    It means the ruler changed, and every comparison to an earlier phase is now
    measuring with a different one.
    """
    records = _subset(suite)
    summary: Summary = summarise(records)
    questions, r5, r20, cov, mrr, top, refusals = PUBLISHED[suite]

    assert summary.questions == questions
    assert _round(summary.recall_at_5) == r5
    assert _round(summary.recall_at_20) == r20
    assert _round(summary.coverage_at_5) == cov
    assert _round(summary.mrr) == mrr
    assert _round(summary.mean_top_score) == top
    assert sum(refused(record) for record in records) == refusals


def test_the_baseline_run_is_present_and_whole() -> None:
    """The pin is worthless if the run it points at can go missing quietly."""
    for name in ("meta.json", "records.jsonl", "judgements.jsonl"):
        assert (BASELINE / name).exists(), f"{name} missing from {BASELINE.name}"
