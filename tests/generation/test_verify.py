"""Tests for the groundedness gate.

Nothing here checks whether the gate catches a real ungrounded claim -- that is
a question about a model, and only `judge-probe` and a paid run can answer it.
What is checked here is the part we wrote: that the checker sees the same
sources the writer saw, and that every way the checker can misbehave leaves the
answer standing rather than destroying it.

The distinction is the Phase 8 lesson. A unit test can assert that the ranking
came from the reranker; it cannot assert the reranker is any good. The same
split applies here, so the guards get tests and the judgement gets a probe.
"""

from eurohistory_rag.generation.client import complete
from eurohistory_rag.generation.verify import (
    REFUSAL,
    build_verify_messages,
    verify,
)
from eurohistory_rag.retrieval.search import SearchResult
from tests.fakes import FakeGenerator, UnavailableGenerator

DRAFT = "Hungary assumed the financial obligations [1]."
FIXED = "Romania, Yugoslavia and Czechoslovakia assumed the obligations [1]."


def reply(answer: str) -> str:
    """A checker reply in the shape verify_prompt.md asks for.

    The working-out block is required, so a fake returning bare text would be
    testing a reply the real prompt never produces.
    """
    return f"""<check>
the claim -- UNSUPPORTED -- the source words
</check>
<answer>
{answer}
</answer>"""


def result(title: str = "Treaty of Trianon") -> SearchResult:
    """A SearchResult identifiable by its title."""
    return SearchResult(
        chunk_id=f"{title}:0:0",
        doc_id=f"{title}:0",
        page_id=1,
        title=title,
        heading="Terms",
        text="Romania, Yugoslavia and Czechoslovakia had to assume part of the "
        "financial obligations.",
        score=0.7,
        revision_id=42,
    )


# --- what the checker is shown ----------------------------------------------


def test_the_checker_sees_the_sources_the_question_and_the_draft() -> None:
    """All three, or it is grading something other than what was written."""
    messages = build_verify_messages("what did Trianon take?", [result()], DRAFT)

    user = messages[1]["content"]
    assert "had to assume part of the financial obligations" in user
    assert "what did Trianon take?" in user
    assert DRAFT in user


def test_the_sources_are_numbered_the_way_the_writer_saw_them() -> None:
    """The draft's [1] has to mean the same source here as it did there."""
    messages = build_verify_messages("q", [result("A"), result("B")], DRAFT)

    assert '<source id="1" title="A ' in messages[1]["content"]
    assert '<source id="2" title="B ' in messages[1]["content"]


# --- the gate doing its job -------------------------------------------------


def test_a_corrected_draft_is_what_ships() -> None:
    """The dead-switch test: if the checker is never called this still passes
    with the draft, so the assertion is on the checker's text specifically.
    """
    checker = FakeGenerator(answer=reply(FIXED))

    checked = verify(checker, "q", [result()], DRAFT)

    assert checked.text == FIXED
    assert checked.changed is True
    assert len(checker.calls) == 1


def test_an_unchanged_draft_is_not_counted_as_a_revision() -> None:
    checker = FakeGenerator(answer=reply(DRAFT))

    checked = verify(checker, "q", [result()], DRAFT)

    assert checked.text == DRAFT
    assert checked.changed is False


def test_rewrapped_whitespace_is_not_a_revision() -> None:
    """Reflowing is not a correction, and counting it would inflate the one
    number that says whether this gate does anything.
    """
    checker = FakeGenerator(
        answer=reply("Hungary assumed the\nfinancial obligations [1].")
    )

    assert verify(checker, "q", [result()], DRAFT).changed is False


# --- every way the checker can misbehave ------------------------------------


def test_an_unreachable_checker_keeps_the_draft() -> None:
    """Fail open. An answer already exists; losing it because the *checker*
    was down would make this change a net loss on the 99% it cannot help.
    """
    checked = verify(UnavailableGenerator(), "q", [result()], DRAFT)

    assert checked.text == DRAFT
    assert checked.changed is False


def test_a_checker_that_returns_nothing_keeps_the_draft() -> None:
    checked = verify(FakeGenerator(answer=reply("   ")), "q", [result()], DRAFT)

    assert checked.text == DRAFT


def test_a_checker_may_not_turn_an_answer_into_a_refusal() -> None:
    """Faithfulness is supported claims over total claims, so an answer with no
    claims scores perfectly. Refusing is the cheapest way for this gate to look
    like it worked, and verify_prompt.md forbidding it is not enough on its own --
    three sightings in this repo of a prompt instruction being ignored.
    """
    checker = FakeGenerator(answer=reply(f"{REFUSAL} The passages cover Versailles."))

    checked = verify(checker, "q", [result()], DRAFT)

    assert checked.text == DRAFT
    assert checked.changed is False


def test_the_cost_is_recorded_even_when_the_revision_is_thrown_away() -> None:
    """The call was paid for either way, and a cost that vanishes on the
    failure path makes the failure path look free.
    """
    checked = verify(FakeGenerator(answer=reply(REFUSAL)), "q", [result()], DRAFT)

    assert checked.prompt_tokens == complete(FakeGenerator(), []).prompt_tokens


def test_a_reply_without_an_answer_block_keeps_the_draft() -> None:
    """A reply cut off by the token ceiling lands here. Without both tags
    there is no way to tell the checker's working out from the answer, and
    shipping its reasoning to a reader is worse than shipping the draft.
    """
    checker = FakeGenerator(answer="<check>\nthe claim -- UNSUPPORTED -- the sou")

    assert verify(checker, "q", [result()], DRAFT).text == DRAFT


# --- answers not worth checking ---------------------------------------------


def test_a_refusal_is_not_sent_to_the_checker() -> None:
    """ "Not in the sources." makes no claims, so there is nothing to check and
    no reason to pay for a call that can only do harm.
    """
    checker = FakeGenerator(answer=reply(FIXED))

    checked = verify(checker, "q", [result()], f"{REFUSAL} The passages cover Berlin.")

    assert checker.calls == []
    assert checked.text.startswith(REFUSAL)


def test_an_empty_draft_is_not_sent_to_the_checker() -> None:
    checker = FakeGenerator(answer=reply(FIXED))

    verify(checker, "q", [result()], "")

    assert checker.calls == []
