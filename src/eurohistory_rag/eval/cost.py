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

from eurohistory_rag.eval.record import RUNS_DIR, EvalRecord, read_records

# Dollars per million tokens, (prompt, completion). A hardcoded price list is a
# thing that goes stale, and this one will: it is here rather than in `Settings`
# because it is not a per-machine setting, and it is small enough to correct in
# one line when OpenAI moves a price. The estimate is a warning before a spend,
# not an invoice -- being 20% wrong is survivable, having no number is not.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
}

# Used when no previous run of this model exists. Taken from the 60-question
# runs of Phase 16: ~2,620 prompt and ~182 completion tokens per question.
FALLBACK_TOKENS = (2620.0, 182.0)


@dataclass(frozen=True, slots=True)
class Estimate:
    """What a run is expected to cost, and where the figure came from."""

    dollars: float
    questions: int
    model: str
    # Plain English, shown next to the number. An estimate whose basis is
    # invisible is an estimate nobody can sanity-check.
    basis: str


def _tokens_per_question(records: list[EvalRecord]) -> tuple[float, float] | None:
    """Mean prompt and completion tokens per question in a finished run."""
    scored = [r for r in records if r.prompt_tokens and r.completion_tokens]
    if not scored:
        return None
    return (
        sum(r.prompt_tokens or 0 for r in scored) / len(scored),
        sum(r.completion_tokens or 0 for r in scored) / len(scored),
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
    prompt_each, completion_each = measured or FALLBACK_TOKENS
    prompt_price, completion_price = PRICES.get(model, PRICES["gpt-4.1-mini"])

    dollars = questions * (
        prompt_each * prompt_price / 1_000_000
        + completion_each * completion_price / 1_000_000
    )
    basis = (
        f"measured: {prompt_each:,.0f} prompt + {completion_each:,.0f} completion "
        f"tokens per question on the last {model} run"
        if measured
        else f"no previous {model} run on disk; using the Phase 16 average"
    )
    return Estimate(
        dollars=round(dollars, 4), questions=questions, model=model, basis=basis
    )
