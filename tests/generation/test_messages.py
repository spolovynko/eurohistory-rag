"""Tests for the message builder.

The prompt itself cannot be unit tested -- whether a rule works is a question
for Phase 7's thirty questions. What can be tested is everything around it:
that the rules arrive as the system message, that sources are wrapped and
numbered the way the prompt promises, and that the question comes last.
"""

from eurohistory_rag.generation.messages import (
    SYSTEM_PROMPT,
    build_messages,
    format_source,
)
from eurohistory_rag.retrieval.search import SearchResult


def result(
    title: str = "Berlin",
    heading: str = "History",
    text: str = "The wall went up in 1961.",
) -> SearchResult:
    """A SearchResult carrying only what the builder reads."""
    return SearchResult(
        chunk_id="1:0:0",
        doc_id="1:0",
        page_id=1,
        title=title,
        heading=heading,
        text=text,
        score=0.7,
        revision_id=42,
    )


# --- one source block -------------------------------------------------------


def test_a_source_block_carries_its_number_and_where_it_came_from() -> None:
    block = format_source(3, result())

    assert block.startswith('<source id="3" title="Berlin — History">')
    assert block.endswith("</source>")
    assert "The wall went up in 1961." in block


def test_a_lead_section_has_no_dash_in_its_title() -> None:
    """`source` already handles this; the builder must not undo it."""
    block = format_source(1, result(heading=""))

    assert block.startswith('<source id="1" title="Berlin">')


def test_a_quote_in_a_heading_does_not_break_the_attribute() -> None:
    """Wikipedia headings contain quotation marks, and an unescaped one would
    end the title attribute early and leave the rest as garbage.
    """
    block = format_source(1, result(heading='The "Iron Curtain"'))

    assert block.startswith('<source id="1" title="Berlin — The \'Iron Curtain\'">')


# --- the whole message list -------------------------------------------------


def test_the_rules_arrive_as_the_system_message() -> None:
    messages = build_messages("why?", [result()])

    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT


def test_the_question_comes_after_the_sources() -> None:
    """A model reads the end of a long message hardest, and five chunks is
    long. Reordering this is a Phase 8 experiment, not an accident.
    """
    messages = build_messages("why was the wall built?", [result()])
    user = messages[1]["content"]

    assert user.index("<source") < user.index("why was the wall built?")
    assert user.rstrip().endswith("why was the wall built?")


def test_numbering_starts_at_one_and_follows_rank_order() -> None:
    """[1] means "first result". Nothing else keeps citations pointing at the
    right chunk once the answer comes back.
    """
    user = build_messages("why?", [result(), result(title="Bonn")])[1]["content"]

    assert user.index('<source id="1" title="Berlin') < user.index('id="2" title="Bonn')


def test_every_source_is_included() -> None:
    user = build_messages("why?", [result() for _ in range(5)])[1]["content"]

    assert user.count("<source id=") == 5
    assert user.count("</source>") == 5


def test_no_sources_says_so_rather_than_leaving_a_gap() -> None:
    """An empty sources section reads like a bug in the builder. Saying it
    plainly is what lets the prompt's refusal rule fire.
    """
    user = build_messages("anything?", [])[1]["content"]

    assert "No sources were found." in user
    assert "<source" not in user


def test_the_prompt_file_was_actually_loaded() -> None:
    """Guards the one thing moving the prompt into markdown put at risk: a
    missing or unpackaged prompt.md would leave this empty.
    """
    assert "# ROLE" in SYSTEM_PROMPT
    assert "Not in the sources." in SYSTEM_PROMPT
