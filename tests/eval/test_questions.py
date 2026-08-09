"""The question set's own rules, and the committed set against them."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from eurohistory_rag.eval.questions import (
    QUESTIONS_PATH,
    SUITE_TARGETS,
    Question,
    Turn,
    counts,
    load_questions,
    unknown_doc_ids,
)


def test_answerable_question_needs_an_answer_key() -> None:
    with pytest.raises(ValidationError, match="no expected ids"):
        Question(id="q1", kind="easy", text="Why?", expected=())


def test_unanswerable_question_must_not_have_one() -> None:
    with pytest.raises(ValidationError, match="has expected ids"):
        Question(id="q1", kind="unanswerable", text="Why?", expected=("1:0",))


def test_expected_ids_must_look_like_doc_ids() -> None:
    with pytest.raises(ValidationError):
        Question(id="q1", kind="easy", text="Why?", expected=("Berlin — History",))


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "questions.toml"
    path.write_text(
        '[[question]]\nid = "a"\nkind = "easy"\ntext = "x"\nexpected = ["1:0"]\n'
        '[[question]]\nid = "a"\nkind = "easy"\ntext = "y"\nexpected = ["2:0"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="duplicate question ids"):
        load_questions(path)


def test_unknown_doc_ids_reports_only_the_missing_ones() -> None:
    questions = (
        Question(id="a", kind="easy", text="x", expected=("1:0", "9:9")),
        Question(id="b", kind="easy", text="y", expected=("2:0",)),
    )
    assert unknown_doc_ids(questions, {"1:0", "2:0"}) == {"a": ["9:9"]}


def test_a_question_belongs_to_the_golden_set_unless_it_says_otherwise() -> None:
    """The default is what keeps the golden thirty byte-identical."""
    assert Question(id="a", kind="easy", text="x", expected=("1:0",)).suite == "golden"


def test_a_synthetic_question_names_its_own_suite() -> None:
    """Its kind already decides it, so a generated file need not repeat it."""
    assert Question(id="a", kind="synthetic", text="x", expected=("1:0",)).suite == (
        "synthetic"
    )


def test_committed_set_loads_and_matches_the_plan() -> None:
    """The real file: every suite in the shape its own plan asks for.

    Each suite is checked rather than the total, because the total is exactly
    what hid Phase 14's problem -- thirty questions about a third of the corpus
    average perfectly well with thirty about the rest. The count is derived from
    SUITE_TARGETS rather than typed, so adding a suite is one edit and not two.
    """
    questions = load_questions(QUESTIONS_PATH)
    assert sorted({q.suite for q in questions}) == sorted(SUITE_TARGETS)
    for suite, want in SUITE_TARGETS.items():
        subset = [question for question in questions if question.suite == suite]
        assert counts(subset) == want, suite
        assert len(subset) == sum(want.values()), suite


def test_the_golden_thirty_are_still_the_golden_thirty() -> None:
    """Phase 22 added eighteen questions and had to leave the sixty untouched.

    Every baseline back to Phase 7 is a comparison against these ids; one of
    them renamed or reworded silently invalidates all of it. Checked on ids
    rather than on file bytes, so a comment may be edited and a question may
    not.
    """
    questions = load_questions(QUESTIONS_PATH)
    golden = [q.id for q in questions if q.suite == "golden"]
    assert golden[0] == "brest-litovsk-terms"
    assert golden[-1] == "transformer-attention"
    assert len(golden) == 30


def test_committed_ground_truth_points_at_real_sections() -> None:
    """Every expected doc_id exists in Silver.

    The failure this catches is invisible otherwise: a typo'd id can never be
    retrieved, so its question scores zero forever and reads as a retrieval
    problem rather than a question-set problem.
    """
    polars = pytest.importorskip("polars")
    silver = Path("data/silver/documents.parquet")
    if not silver.exists():
        pytest.skip("Silver not built")
    known = set(polars.read_parquet(silver, columns=["doc_id"])["doc_id"].to_list())
    assert unknown_doc_ids(load_questions(QUESTIONS_PATH), known) == {}


# --- conversation -----------------------------------------------------------


def test_a_conversation_question_must_carry_its_history() -> None:
    """Without it the case is a single-turn question hiding in the suite that
    exists to measure follow-ups."""
    with pytest.raises(ValidationError, match="no history"):
        Question(
            id="c1",
            kind="easy",
            text="When did it come down?",
            expected=("3722:8",),
            suite="conversation",
        )


def test_history_outside_the_conversation_suite_is_refused() -> None:
    """The golden, extended, temporal and factual tables are the control.

    A history attached to one of them would move a question those tables exist
    to hold still, and it would move it invisibly.
    """
    with pytest.raises(ValidationError, match="outside the conversation suite"):
        Question(
            id="q1",
            kind="easy",
            text="Why?",
            expected=("1:0",),
            history=(Turn(user="and?", assistant="yes"),),
        )


def test_the_committed_conversation_cases_all_have_an_exchange() -> None:
    """Read from the file rather than asserted about it in the abstract."""
    conversation = [
        q for q in load_questions(QUESTIONS_PATH) if q.suite == "conversation"
    ]

    assert len(conversation) == 14
    assert all(q.history for q in conversation)
    assert all(turn.assistant.strip() for q in conversation for turn in q.history)


def test_the_three_controls_repeat_a_question_that_already_exists() -> None:
    """The impossible check for this suite, guarded so it cannot silently rot.

    Each control's text is copied verbatim from a question in another suite. In
    a run with no rewriting the pair must retrieve identically, and that is only
    a meaningful check while the two strings stay equal.
    """
    questions = load_questions(QUESTIONS_PATH)
    by_id = {q.id: q for q in questions}
    pairs = {
        "c-shift-wannsee": "wannsee-decisions",
        "c-shift-moscow": "stopped-short-of-moscow",
        "c-shift-easter-rising": "f-easter-rising-deaths",
    }

    for control, twin in pairs.items():
        assert by_id[control].text == by_id[twin].text
        assert by_id[control].expected == by_id[twin].expected
        assert by_id[control].expected_answer == by_id[twin].expected_answer
