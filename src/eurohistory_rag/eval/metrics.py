"""Turning a run into numbers.

Every metric here is computed from records alone -- no model call, no network,
no judgement. That is the line: what a machine can count lives in this module,
and what only a person can decide stays out of it and goes in the scores file.
"""

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from statistics import mean

from eurohistory_rag.eval.record import EvalRecord

# The wordings a refusal opens with, and they are read out of `system_prompt.md`
# rather than guessed. The prompt gives the model two ways to decline and this
# constant knew only one of them: rule 3 says begin with exactly "Not in the
# sources.", and rule 2 says a partial answer should *end* with a sentence
# beginning "The sources do not cover". An answer that declines the whole
# question in rule 2's words was scored as an answer -- three times on the
# record, twice of them live in Phase 26, where two treaty dates stopped being
# answered and the refusal count did not move.
#
# The third entry is not in the prompt. It is what the model actually writes,
# found by reading all 1,780 answers on disk, and it is here because the list is
# closed on purpose: a wording nobody has seen is a miss this metric reports as
# its own error rate, not a hole a wider regex quietly papers over. D-102.
REFUSAL_OPENERS = (
    "not in the sources",
    "the sources do not cover",
    "the sources do not provide",
)

# Where a sentence ends. Crude on purpose -- an abbreviation would split early,
# and the only thing read from the split is whether the *first* sentence
# declines, which no abbreviation in this corpus can change.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


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
    """Did the answer decline the question, rather than answer part of it?

    **Position, not wording.** `system_prompt.md` uses the same sentence for two
    opposite outcomes: a refusal *opens* with "the sources do not cover", and a
    partial answer -- a real answer, with citations -- *ends* with it. Matching
    the phrase anywhere cannot tell them apart, and matching one hardcoded phrase
    could not see the second wording at all.

    So only the first sentence is read. Checked against every answer this
    repository has ever recorded: of 224 distinct answers containing any decline
    wording, every one that declines in sentence one is a genuine refusal and
    every one that declines only later is a genuine answer. D-102.
    """
    leading = _SENTENCE_END.split(record.answer.strip(), maxsplit=1)[0].lower()
    return any(phrase in leading for phrase in REFUSAL_OPENERS)


def _flatten(text: str) -> str:
    """Lowercase, with thousands commas removed.

    So that `41,291` and `41291` are the same figure, which they are: the
    infobox writes one and the prose the other, and a comparison that called
    them different would have scored the Switzerland control wrong.

    **Spaces are kept, and the first version of this function removed them.**
    That version scored `f-hungary-1956-soviet-dead` as not stating 699 while
    the answer opened "in 1956, 699 Soviet soldiers were killed": with the comma
    and the space gone the text read `1956699`, so the digit-boundary guard
    below saw 699 sitting inside a longer number and refused it. The
    normalisation manufactured the collision the guard exists to catch. Found by
    reading the answer next to the verdict, not by any test. D-097.
    """
    return text.lower().replace(",", "")


def states_fact(record: EvalRecord) -> bool | None:
    """Did the answer state the value the question asked for?

    None when the question asks for no particular value, which is most of them
    -- an explanation is judged by whether the right section came back, and this
    metric would report a meaningless False for it.

    A bare number is matched at digit boundaries, so an answer saying "1,485"
    does not count as stating "485". Everything else is a plain substring: the
    answer is prose and the fact can be phrased into it any number of ways.
    """
    if not record.expected_answers:
        return None
    answer = _flatten(record.answer)
    return any(
        re.search(_boundaries(_flatten(wanted)), answer)
        for wanted in record.expected_answers
    )


def _boundaries(wanted: str) -> str:
    """The expected form as a regex, guarded against landing inside a number."""
    pattern = re.escape(wanted)
    if wanted[:1].isdigit():
        pattern = r"(?<!\d)" + pattern
    if wanted[-1:].isdigit():
        pattern = pattern + r"(?!\d)"
    return pattern


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


def first_token_ms(record: EvalRecord) -> float:
    """How long the caller waited before *any* of the answer existed.

    The number a person actually experiences as "slow", which total time is
    not: an answer that starts in one second and finishes in five feels quicker
    than one that appears whole at four.

    A run made before streaming existed recorded no such moment, and the honest
    value for it is the whole question -- on that path the first character of
    the answer became available at the same instant the last one did. So an
    absent value falls back to `total_ms` rather than to zero, which is what
    makes every run already on disk a valid "before". D-095.
    """
    return record.total_ms if record.first_token_ms is None else record.first_token_ms


@dataclass(frozen=True, slots=True)
class Summary:
    """One run reduced to the numbers worth comparing between runs."""

    kind: str
    questions: int
    recall_at_5: float | None
    recall_at_20: float | None
    coverage_at_5: float | None
    mrr: float | None
    # The share of questions asking for a stated value whose answer states it,
    # and how many such questions there were. None when the set contains none,
    # which is every suite but the factual one -- reporting 0.0 there would read
    # as a failure rather than as "not applicable". D-097.
    fact_rate: float | None
    fact_questions: int
    mean_top_score: float
    mean_distinct_docs_at_5: float
    mean_distinct_articles_at_5: float
    refusal_rate: float
    answers_with_no_citation: int
    answers_with_invalid_marker: int
    p50_total_ms: float
    p95_total_ms: float
    p50_first_token_ms: float
    mean_search_ms: float
    mean_generate_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    # The cached share of `prompt_tokens`, in tokens. None on every run made
    # before Phase 29, where it means the field was never read rather than that
    # nothing was cached -- the distinction matters because a 0 here would say
    # the project paid full price, and it did not. D-103.
    cached_tokens: int | None
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
    with_facts = [r for r in records if r.expected_answers]
    totals = [r.total_ms for r in records]
    prompts = [r.prompt_tokens for r in records if r.prompt_tokens is not None]
    completions = [
        r.completion_tokens for r in records if r.completion_tokens is not None
    ]
    cached = [r.cached_tokens for r in records if r.cached_tokens is not None]

    return Summary(
        kind=kind,
        questions=len(records),
        recall_at_5=mean(hit_at(r, 5) for r in scored) if scored else None,
        recall_at_20=mean(hit_at(r, 20) for r in scored) if scored else None,
        coverage_at_5=mean(coverage_at(r, 5) for r in scored) if scored else None,
        mrr=mean(reciprocal_rank(r) for r in scored) if scored else None,
        fact_rate=(
            mean(bool(states_fact(r)) for r in with_facts) if with_facts else None
        ),
        fact_questions=len(with_facts),
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
        p50_first_token_ms=_percentile([first_token_ms(r) for r in records], 0.50),
        mean_search_ms=mean(r.search_ms for r in records) if records else 0.0,
        mean_generate_ms=mean(r.generate_ms for r in records) if records else 0.0,
        prompt_tokens=sum(prompts) if prompts else None,
        completion_tokens=sum(completions) if completions else None,
        cached_tokens=sum(cached) if cached else None,
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
