"""What the next run will cost, worked out from the last one.

D-083 requires the price to be stated before it is spent. At a terminal that is
a sentence in a chat message; behind a button it has to be a number the server
computes, because nobody types a cost estimate into a dialog they are about to
confirm.

The estimate is measured rather than guessed: a previous run recorded exactly
how many tokens sixty questions consumed, so the arithmetic is that run's
tokens per question times this run's question count times the published price.
"""

from dataclasses import dataclass
from pathlib import Path

from eurohistory_rag.core.spend import PRICES, dollars
from eurohistory_rag.eval.record import RUNS_DIR, EvalRecord, read_records

# `PRICES` and `dollars` used to live here and moved to `core/spend.py` in Phase
# 30. They are imported back rather than re-typed because this module's job is
# unchanged -- it is still what quotes a run before anyone agrees to pay for it
# -- but the ceiling that refuses a run has to apply the same price list, and
# `generation/` cannot import anything under `eval/` without a cycle: this file
# imports `eval/record.py`, which imports `generation/rewrite.py`. Re-exported
# so that every existing caller of `eval.cost.dollars` keeps working. D-104.
__all__ = ["FALLBACK_TOKENS", "PRICES", "Estimate", "dollars", "estimate"]

# Used when no previous run of this model exists. Taken from the 60-question
# runs of Phase 16: ~2,620 prompt and ~182 completion tokens per question. The
# cached figure is 0 on purpose: a fallback that assumed a discount would
# under-warn, and under-warning before a spend is the one direction that costs
# somebody money they did not agree to.
FALLBACK_TOKENS = (2620.0, 182.0, 0.0)


@dataclass(frozen=True, slots=True)
class Estimate:
    """What a run is expected to cost, and where the figure came from."""

    dollars: float
    questions: int
    model: str
    # Plain English, shown next to the number. An estimate whose basis is
    # invisible is an estimate nobody can sanity-check.
    basis: str


def _tokens_per_question(
    records: list[EvalRecord],
) -> tuple[float, float, float] | None:
    """Mean prompt, completion and cached tokens per question in a finished run.

    Cached tokens are averaged over the same questions as the other two rather
    than over the ones that reported a cache hit, because the estimate wants the
    discount a whole run gets -- and the first call of a run is a cache miss by
    definition, so an average over hits only would promise a saving no run can
    achieve.
    """
    scored = [r for r in records if r.prompt_tokens and r.completion_tokens]
    if not scored:
        return None
    return (
        sum(r.prompt_tokens or 0 for r in scored) / len(scored),
        sum(r.completion_tokens or 0 for r in scored) / len(scored),
        sum(r.cached_tokens or 0 for r in scored) / len(scored),
    )


def last_run_with(model: str, runs_dir: Path = RUNS_DIR) -> list[EvalRecord] | None:
    """The newest run that answered with this model, or None.

    Matched on the model because token counts are not transferable between
    them: the prompt is the same size, but a model that reasons before
    answering spends several times the completion tokens of one that does not.
    """
    if not runs_dir.is_dir():
        return None
    for directory in sorted(runs_dir.iterdir(), reverse=True):
        if not (directory / "records.jsonl").exists():
            continue
        records = read_records(directory)
        if records and records[0].generation_model == model:
            return records
    return None


def estimate(model: str, questions: int, runs_dir: Path = RUNS_DIR) -> Estimate:
    """What `questions` questions will cost this model, in dollars.

    Embeddings are left out on purpose. One query embedding is about twenty
    tokens at $0.02 per million, so sixty of them come to roughly one
    fifty-thousandth of a cent, and putting it in the sum would suggest a
    precision this figure does not have.
    """
    records = last_run_with(model, runs_dir)
    measured = _tokens_per_question(records) if records else None
    prompt_each, completion_each, cached_each = measured or FALLBACK_TOKENS

    total = questions * dollars(
        round(prompt_each), round(cached_each), round(completion_each), model
    )
    share = f", {cached_each / prompt_each:.0%} of it cached" if cached_each else ""
    basis = (
        f"measured: {prompt_each:,.0f} prompt + {completion_each:,.0f} completion "
        f"tokens per question on the last {model} run{share}"
        if measured
        else f"no previous {model} run on disk; using the Phase 16 average"
    )
    return Estimate(
        dollars=round(total, 4), questions=questions, model=model, basis=basis
    )
