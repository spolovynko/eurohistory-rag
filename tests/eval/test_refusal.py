"""The refusal test, held against every answer this repository has recorded.

`metrics.refused` is the third metric in this project to be fixed after it was
found lying. Phase 7's version reported 0% refusals because the phrase had been
guessed; this one reported 9 while two answers stopped answering, because it knew
one of the two wordings `system_prompt.md` actually uses.

A unit test on invented strings would not have caught either. So the ground truth
here is the corpus of real answers on disk: a deliberately **wider** net than the
metric, run over all 27 runs, asserting that nothing it catches in a first
sentence is something the metric misses. When the prompt grows a third way to
decline, this fails on the day a run recording it is committed -- which is the
earliest anything could. D-102.
"""

import re
from pathlib import Path

import pytest

from eurohistory_rag.eval.metrics import REFUSAL_OPENERS, refused
from eurohistory_rag.eval.record import EvalRecord, read_records

RUNS = Path(__file__).parents[2] / "eval" / "runs"

# Deliberately looser than REFUSAL_OPENERS, and hand-written rather than derived
# from it -- a net built out of the thing it is checking would agree with it by
# construction and prove nothing.
LOOSE = re.compile(
    r"not in the sources|do not cover|don't cover|do not provide|do not specify"
    r"|do not contain|do not mention|do not include|do not state|do not give"
    r"|do not say|no information|not covered|not detailed|cannot be answered"
    r"|do not address|do not detail|do not offer|do not discuss|do not describe"
    r"|do not explain|silent on|make no mention|nothing about",
    re.IGNORECASE,
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s")

# The one answer on disk where the wider net fires in sentence one and the metric
# does not, named in the prediction before the rule was written rather than
# discovered afterwards. It declines the question asked -- the ethnic groups in
# the 2001 census -- and then answers a neighbouring one about language, with a
# citation, so it is arguable in both directions. It is the metric's known error
# rate: 1 answer of 224 that carry any decline wording.
KNOWN_MISS = "syn-1025103-4-0"


def _runs() -> list[Path]:
    """Every run directory that has records, newest last."""
    return sorted(
        d for d in RUNS.iterdir() if d.is_dir() and (d / "records.jsonl").is_file()
    )


def _leading(answer: str) -> str:
    """The answer's first sentence."""
    return _SENTENCE_END.split(answer.strip(), maxsplit=1)[0]


def _record(answer: str) -> EvalRecord:
    """A record carrying nothing but an answer, which is all `refused` reads."""
    return EvalRecord(
        question_id="q",
        question="q",
        kind="easy",
        expected_doc_ids=[],
        retrieved=[],
        answer=answer,
        generation_model="test",
        sources_sent=0,
        markers_found=[],
        citations=[],
        search_ms=0.0,
        generate_ms=0.0,
        total_ms=0.0,
    )


# Both halves quoted verbatim out of eval/runs/, so the test cannot drift from
# what the model writes. The first is a whole-question refusal worded the way the
# old metric could not see; the second is a partial answer that ends the way the
# prompt tells it to and must never be counted as a refusal.
REFUSAL_IN_SENTENCE_ONE = (
    "The sources do not cover what NATO agreed at its 2023 summit in Vilnius. "
    "They mention that the 2023 NATO summit was held in Vilnius [1][2], but do "
    "not specify any agreements made at that summit."
)
ANSWER_WITH_A_DECLINING_TAIL = (
    "The Locarno Treaties were formally signed in London on 1 December 1925 [3]. "
    "The sources do not explicitly state the exact date the treaties entered "
    "into force, only the signing date."
)


def test_a_refusal_worded_the_second_way_is_counted() -> None:
    """The defect this phase exists for, in the answer that exposed it."""
    assert refused(_record(REFUSAL_IN_SENTENCE_ONE))


def test_a_partial_answer_that_ends_by_declining_is_not_a_refusal() -> None:
    """The other half, and the reason the phrase alone can never be the test.

    This answer states a date, cites it, and then says what is missing -- which
    is what `system_prompt.md` rule 2 asks for. A phrase match anywhere calls it
    a refusal and loses a real answer.
    """
    assert not refused(_record(ANSWER_WITH_A_DECLINING_TAIL))


def test_the_prompts_own_opening_still_counts() -> None:
    """Rule 3's verbatim opener, which the old metric did catch."""
    assert refused(_record("Not in the sources. The passages cover Berlin."))


def test_an_ordinary_answer_is_not_a_refusal() -> None:
    assert not refused(_record("The wall went up in August 1961 [1]."))


@pytest.mark.parametrize("run", _runs(), ids=lambda d: d.name)
def test_no_recorded_refusal_is_worded_in_a_way_the_metric_misses(run: Path) -> None:
    """The wider net must find nothing in a first sentence that the metric misses.

    This is the check that will fail the day the prompt learns a third way to
    decline, and it fails on a real answer rather than on an invented one.
    """
    missed = [
        record.question_id
        for record in read_records(run)
        if LOOSE.search(_leading(record.answer)) and not refused(record)
    ]
    assert all(name == KNOWN_MISS for name in missed), missed


@pytest.mark.parametrize("run", _runs(), ids=lambda d: d.name)
def test_the_new_test_catches_everything_the_old_one_did(run: Path) -> None:
    """The impossible check, as a test: a refusal count can never fall.

    Every answer the old rule caught opens with "Not in the sources.", which is
    in `REFUSAL_OPENERS` and sits in position one -- so the new test is a strict
    superset by construction. A run where it is not means the superset property
    was broken, and every before/after in `decisions.md` becomes incomparable.
    """
    for record in read_records(run):
        if "not in the sources" in record.answer.lower():
            assert refused(record), record.question_id


def test_every_opener_is_lowercase_and_matched_case_insensitively() -> None:
    """`refused` lowercases the sentence, so an uppercase entry never matches.

    A silent no-op is exactly how a metric goes wrong without anyone noticing,
    which is the failure this whole module exists to prevent.
    """
    assert all(phrase == phrase.lower() for phrase in REFUSAL_OPENERS)
    assert refused(_record("NOT IN THE SOURCES. The passages cover Berlin."))
