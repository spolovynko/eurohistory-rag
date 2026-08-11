"""HyDE turns a question into the text that gets searched with.

Every test here is about what leaves the module, because that string is what
reaches the embedder. The quality of the hypothesis itself is not testable
without a model and is measured by recall in the sweep, not asserted here.
"""

from eurohistory_rag.generation.hyde import (
    MAX_HYPOTHESIS_CHARS,
    MIN_HYPOTHESIS_CHARS,
    build_messages,
    clean,
    hypothesise,
)
from tests.fakes import FakeGenerator, UnavailableGenerator

QUESTION = "why did people's money stop being worth anything?"

PASSAGE = (
    "The hyperinflation of 1923 destroyed the value of the German mark. Faced "
    "with reparations under the Treaty of Versailles and the occupation of the "
    "Ruhr, the Weimar government financed passive resistance by printing "
    "currency, and prices doubled within days."
)


def test_hypothesis_is_prepended_to_the_question_by_default() -> None:
    """The default keeps the reader's words in front of the guess."""
    result = hypothesise(FakeGenerator(PASSAGE), QUESTION)

    assert result.used
    assert result.text.startswith(QUESTION)
    assert PASSAGE in result.text


def test_hypothesis_alone_drops_the_question() -> None:
    """The paper's form: only the made-up passage is searched with."""
    result = hypothesise(FakeGenerator(PASSAGE), QUESTION, keep_question=False)

    assert result.text == PASSAGE
    assert QUESTION not in result.text


def test_passage_is_kept_separately_from_what_is_searched() -> None:
    """A run must be readable afterwards to ask whether the guess was sane."""
    result = hypothesise(FakeGenerator(PASSAGE), QUESTION)

    assert result.passage == PASSAGE


def test_unreachable_model_falls_back_to_the_question() -> None:
    """A broken hypothesis writer degrades to Phase 5, not to no retrieval."""
    result = hypothesise(UnavailableGenerator(), QUESTION)

    assert result.text == QUESTION
    assert result.used is False
    assert result.passage == ""


def test_a_one_line_answer_is_rejected_and_not_searched_with() -> None:
    """The failure mode is the model restating the question back at us."""
    result = hypothesise(FakeGenerator("Because of inflation."), QUESTION)

    assert result.text == QUESTION
    assert result.used is False
    # Kept for reading even though it was not used, which is the whole point of
    # the two fields being separate.
    assert result.passage == "Because of inflation."


def test_an_essay_is_rejected() -> None:
    """A query much longer than a chunk compares a page against a paragraph."""
    result = hypothesise(FakeGenerator("word " * 400), QUESTION)

    assert result.text == QUESTION
    assert result.used is False


def test_clean_collapses_whitespace_and_holds_the_bounds() -> None:
    """Line breaks in a generated passage would otherwise reach the embedder."""
    # A newline is collapsed, not rejected: a model that lays its paragraph out
    # over several lines has still written a paragraph.
    assert clean(PASSAGE.replace(". ", ".\n\n")) == PASSAGE
    assert clean("x" * (MIN_HYPOTHESIS_CHARS - 1)) is None
    assert clean("x" * (MAX_HYPOTHESIS_CHARS + 1)) is None
    assert clean(f"  {PASSAGE}  ") == PASSAGE


def test_the_question_is_the_only_thing_the_model_is_shown() -> None:
    """No history, no retrieved chunks: HyDE runs before anything is fetched."""
    system, user = build_messages(QUESTION)

    assert system["role"] == "system"
    assert QUESTION in user["content"]
