"""Tests for reading saved runs off disk.

Every case writes a real run directory into `tmp_path` rather than reading the
project's own `eval/runs/`. A test that depends on data somebody produced in
Phase 15 starts failing the day that directory is tidied, and it would be
failing about the wrong thing.
"""

from pathlib import Path

from eurohistory_rag.eval.browse import list_runs, load_run
from eurohistory_rag.eval.record import EvalRecord, Retrieved, RunMeta, write_run

# --- helpers ----------------------------------------------------------------


def meta(run_id: str, **overrides: object) -> RunMeta:
    fields: dict[str, object] = {
        "run_id": run_id,
        "started_at": run_id,
        "git_sha": "abc1234",
        "embedding_model": "text-embedding-3-small",
        "generation_model": "gpt-4.1-mini",
        "collection": "chunks",
        "points": 54903,
        "k": 5,
        "max_per_document": 2,
        "overfetch": 4,
        "reranker": "cross-encoder/ms-marco-MiniLM-L6-v2",
    }
    fields.update(overrides)
    return RunMeta(**fields)  # type: ignore[arg-type]


def retrieved(doc_id: str, rank: int) -> Retrieved:
    return Retrieved(
        rank=rank,
        chunk_id=f"{doc_id}:0",
        doc_id=doc_id,
        page_id=int(doc_id.split(":")[0]),
        source="Treaty of Trianon — Terms",
        score=0.7 - rank * 0.01,
    )


def record(
    question_id: str,
    *,
    kind: str = "easy",
    suite: str = "golden",
    expected: list[str] | None = None,
    hit_rank: int | None = 1,
    answer: str = "Hungary lost territory [1].",
    total_ms: float = 4000.0,
) -> EvalRecord:
    """One record whose first correct chunk sits at `hit_rank`, or nowhere."""
    keys = ["100:1"] if expected is None else expected
    hits = [retrieved(f"999:{i}", i) for i in range(1, 21)]
    if hit_rank is not None and keys:
        hits[hit_rank - 1] = retrieved(keys[0], hit_rank)
    return EvalRecord(
        question_id=question_id,
        question="What did Trianon do?",
        kind=kind,
        expected_doc_ids=keys,
        retrieved=hits,
        answer=answer,
        generation_model="gpt-4.1-mini",
        sources_sent=5,
        markers_found=[1],
        citations=[],
        search_ms=300.0,
        generate_ms=total_ms - 300.0,
        total_ms=total_ms,
        suite=suite,
    )


def write(root: Path, run_meta: RunMeta, records: list[EvalRecord]) -> Path:
    """A run on disk under `root`, exactly as `evaluate` leaves one."""
    return write_run(run_meta, records, root)


# --- listing ----------------------------------------------------------------


def test_runs_are_listed_newest_first(tmp_path: Path) -> None:
    """Run directories are named for their timestamp, so name order is date order."""
    for run_id in ("2026-08-01T1000Z", "2026-08-05T1000Z", "2026-08-03T1000Z"):
        write(tmp_path, meta(run_id), [record("q1")])

    assert [listing.run_id for listing in list_runs(tmp_path)] == [
        "2026-08-05T1000Z",
        "2026-08-03T1000Z",
        "2026-08-01T1000Z",
    ]


def test_a_stray_file_is_not_a_run(tmp_path: Path) -> None:
    """`eval/runs/` also holds notes like gate-D-089.txt, which are not runs."""
    write(tmp_path, meta("2026-08-01T1000Z"), [record("q1")])
    (tmp_path / "gate-D-089.txt").write_text("notes", encoding="utf-8")
    (tmp_path / "half-finished").mkdir()

    assert [listing.run_id for listing in list_runs(tmp_path)] == ["2026-08-01T1000Z"]


def test_listing_a_missing_directory_is_empty_not_an_error(tmp_path: Path) -> None:
    assert list_runs(tmp_path / "nothing-here") == []


def test_a_listing_carries_the_conditions_that_identify_a_run(tmp_path: Path) -> None:
    """Phase 8's dead switch is why `reranker` is on the picker at all."""
    write(
        tmp_path,
        meta("2026-08-01T1000Z", reranker="", points=30362),
        [record("q1"), record("q2")],
    )

    listing = list_runs(tmp_path)[0]

    assert listing.questions == 2
    assert listing.points == 30362
    assert listing.reranker == ""


# --- one run ----------------------------------------------------------------


def test_a_run_is_scored_per_suite_and_overall(tmp_path: Path) -> None:
    """Phase 15 kept the golden thirty separable; the view must keep them so."""
    write(
        tmp_path,
        meta("r"),
        [
            record("g1", suite="golden", hit_rank=1),
            record("e1", suite="extended", hit_rank=9),
        ],
    )

    view = load_run("r", tmp_path)

    assert view is not None
    assert set(view.suites) == {"all", "golden", "extended"}
    golden = view.suites["golden"][-1]
    extended = view.suites["extended"][-1]
    assert golden.recall_at_5 == 1.0
    assert extended.recall_at_5 == 0.0


def test_the_last_row_of_a_suite_is_the_overall_one(tmp_path: Path) -> None:
    """The page reads `rows[rows.length - 1]` for its cards, so order matters."""
    write(
        tmp_path,
        meta("r"),
        [record("a", kind="easy"), record("b", kind="multi", hit_rank=11)],
    )

    view = load_run("r", tmp_path)

    assert view is not None
    rows = view.suites["all"]
    assert [row.kind for row in rows] == ["easy", "multi", "all"]
    assert rows[-1].questions == 2


def test_a_question_outcome_says_where_the_first_hit_was(tmp_path: Path) -> None:
    """75% recall@5 does not say whether the misses were at rank 6 or rank 18."""
    write(
        tmp_path,
        meta("r"),
        [
            record("near", hit_rank=3),
            record("deep", hit_rank=11),
            record("gone", hit_rank=None),
        ],
    )

    view = load_run("r", tmp_path)

    assert view is not None
    outcomes = {q.question_id: q for q in view.questions}
    assert (outcomes["near"].first_hit_rank, outcomes["near"].hit_at_5) == (3, True)
    assert (outcomes["deep"].first_hit_rank, outcomes["deep"].hit_at_5) == (11, False)
    assert (outcomes["gone"].first_hit_rank, outcomes["gone"].hit_at_5) == (None, False)


def test_an_unanswerable_question_is_marked_unscored(tmp_path: Path) -> None:
    """No answer key is not a miss. Reporting 0% for a refusal case reads as failure."""
    write(
        tmp_path,
        meta("r"),
        [
            record(
                "refuse", kind="unanswerable", expected=[], answer="Not in the sources."
            )
        ],
    )

    view = load_run("r", tmp_path)

    assert view is not None
    outcome = view.questions[0]
    assert outcome.scored is False
    assert outcome.first_hit_rank is None
    assert outcome.refused is True


def test_an_unknown_run_is_none_rather_than_an_error(tmp_path: Path) -> None:
    assert load_run("2026-01-01T0000Z", tmp_path) is None


def test_a_run_id_cannot_climb_out_of_the_runs_directory(tmp_path: Path) -> None:
    """`run_id` arrives from a URL, so it is matched against what exists.

    A name is never joined onto a path and trusted to stay inside it.
    """
    write(tmp_path / "runs", meta("r"), [record("q1")])
    (tmp_path / "secret.txt").write_text("not yours", encoding="utf-8")

    assert load_run("../secret.txt", tmp_path / "runs") is None
    assert load_run("..", tmp_path / "runs") is None
