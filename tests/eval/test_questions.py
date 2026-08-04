"""The question set's own rules, and the committed set against them."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from eurohistory_rag.eval.questions import (
    QUESTIONS_PATH,
    TARGET_COUNTS,
    Question,
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


def test_committed_set_loads_and_matches_the_plan() -> None:
    """The real file, checked against the 8/8/8/6 the plan asks for."""
    questions = load_questions(QUESTIONS_PATH)
    assert len(questions) == 30
    assert counts(questions) == TARGET_COUNTS


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
