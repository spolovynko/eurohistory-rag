"""Tests for turning a follow-up back into a question.

Nothing here calls a model. What is being checked is the two ways this can be
wrong: leaving a pointer unresolved, which is the failure the phase started
from, and rewriting a question that did not need it, which is the failure the
phase can *cause*. The second is the dangerous one, because it moves questions
nobody was looking at.
"""

from eurohistory_rag.generation.rewrite import (
    ANSWER_CHARS,
    HISTORY_TURNS,
    MAX_QUESTION_CHARS,
    Turn,
    build_messages,
    clean,
    rewrite,
)
from tests.fakes import FakeGenerator, UnavailableGenerator

WALL = Turn(
    user="Why was the Berlin Wall built?",
    assistant="The Berlin Wall was built to stop East Germans fleeing west [1].",
)


def test_a_follow_up_is_replaced_by_what_the_model_wrote() -> None:
    """The whole feature, in one assertion."""
    generator = FakeGenerator("When did the Berlin Wall come down?")

    assert (
        rewrite(generator, "When did it come down?", [WALL])
        == "When did the Berlin Wall come down?"
    )


def test_a_first_turn_is_never_sent_to_the_model() -> None:
    """No history, no rewrite, and no call -- so no cost and nothing to break.

    This is what keeps all 92 single-turn evaluation questions on the path they
    have taken since Phase 6, and the assertion that matters is the empty call
    list rather than the returned string.
    """
    generator = FakeGenerator("something else entirely")

    assert rewrite(generator, "What was the Marshall Plan?", []) == (
        "What was the Marshall Plan?"
    )
    assert generator.calls == []


def test_an_unreachable_rewriter_falls_back_to_the_question_as_typed() -> None:
    """A dead rewriter degrades the conversation; it does not break the answer.

    The alternative is a 503 for a question the corpus and the answering model
    could both have handled, which is a worse failure than a poorly resolved
    pronoun.
    """
    assert (
        rewrite(UnavailableGenerator(), "When did it come down?", [WALL])
        == "When did it come down?"
    )


def test_only_the_last_two_exchanges_are_shown() -> None:
    """The context window decision, asserted rather than described.

    Older turns are dropped rather than summarised: a summary is a second model
    call whose mistakes are invisible, where a dropped turn fails in the open as
    a pronoun that did not resolve.
    """
    turns = [Turn(user=f"q{n}", assistant=f"a{n}") for n in range(5)]
    content = build_messages("and then?", turns)[1]["content"]

    assert "q4" in content and "q3" in content
    assert "q2" not in content
    assert content.count("user:") == HISTORY_TURNS


def test_a_long_answer_is_truncated_before_it_is_sent() -> None:
    """A follow-up points at a name, and an answer states its subject early."""
    long = Turn(user="what happened?", assistant="x" * (ANSWER_CHARS + 500))
    content = build_messages("and then?", [long])[1]["content"]

    assert content.count("x") == ANSWER_CHARS


def test_the_message_being_rewritten_comes_last() -> None:
    """Position is the strongest instruction there is.

    Put in the middle, the message to rewrite is one more turn to summarise;
    put last and labelled, it is the thing being asked about -- the same reason
    the answer prompt ends with its question rather than opening with it.
    """
    content = build_messages("When did it come down?", [WALL])[1]["content"]

    assert content.rstrip().endswith("last message: When did it come down?")


# --- the ways a rewrite is rejected -----------------------------------------


def test_an_explanation_instead_of_a_question_is_rejected() -> None:
    """The model answering, or explaining itself, is long. A question is not."""
    assert clean("x" * (MAX_QUESTION_CHARS + 1), "who led it?") == "who led it?"


def test_several_lines_are_rejected() -> None:
    """One question was asked for. Two lines is the model doing something else."""
    assert clean("Who led Solidarity?\nDo you mean...", "who led it?") == "who led it?"


def test_an_empty_rewrite_is_rejected() -> None:
    """Nothing at all is not a question, and searching for "" returns nothing."""
    assert clean("   ", "who led it?") == "who led it?"


def test_surrounding_quotes_are_stripped_rather_than_searched_for() -> None:
    """A quoted question is the right answer wearing punctuation.

    Rejecting it would throw away a good rewrite; embedding it would search for
    a string nobody wrote. Stripping is the only option that keeps the rewrite.
    """
    assert clean('"Who led Solidarity?"', "who led it?") == "Who led Solidarity?"
