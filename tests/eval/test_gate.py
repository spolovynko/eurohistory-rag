"""The regression gate, checked against runs built by hand.

Every case here writes two real run directories to a temporary path and gates
one against the other, because the thing being tested is a decision made from
files on disk and a gate that only works on objects in memory has never been
tested doing its job.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from eurohistory_rag.eval import judge as judge_module
from eurohistory_rag.eval.gate import TOP_SCORE_FLOOR, gate, read_meta, render
from eurohistory_rag.eval.judge import Claim, Judgement
from eurohistory_rag.eval.record import CitationRef, EvalRecord, Retrieved, RunMeta

ANSWER = "The treaty ended the war [1]."
REFUSAL = "Not in the sources."


def make_record(
    *,
    question_id: str = "q1",
    suite: str = "golden",
    expected: list[str] | None = None,
    doc_ids: list[str] | None = None,
    answer: str = ANSWER,
    top_score: float = 0.700,
    total_ms: float = 4000.0,
    error: str | None = None,
) -> EvalRecord:
    """An EvalRecord carrying only what the gate reads."""
    docs = doc_ids if doc_ids is not None else ["1:0", "2:0", "3:0"]
    return EvalRecord(
        question_id=question_id,
        question="why?",
        kind="easy",
        suite=suite,
        expected_doc_ids=expected if expected is not None else ["1:0"],
        retrieved=[
            Retrieved(
                rank=i,
                chunk_id=f"{doc}:{i}",
                doc_id=doc,
                page_id=int(doc.split(":")[0]),
                source=f"Article {doc}",
                score=top_score - (i - 1) / 100,
            )
            for i, doc in enumerate(docs, start=1)
        ],
        answer=answer,
        generation_model="fake",
        sources_sent=3,
        markers_found=[1],
        citations=[CitationRef(number=1, doc_id=docs[0], source="Article")],
        search_ms=100.0,
        generate_ms=total_ms - 100.0,
        total_ms=total_ms,
        error=error,
    )


def make_meta(run_id: str = "run", **overrides: object) -> RunMeta:
    """A RunMeta with every comparability field set to a known value."""
    meta = RunMeta(
        run_id=run_id,
        started_at="2026-08-07T00:00:00+00:00",
        git_sha="abc1234",
        embedding_model="text-embedding-3-small",
        generation_model="gpt-4.1-mini",
        collection="chunks",
        points=54903,
        k=5,
        max_per_document=2,
        overfetch=4,
        reranker="cross-encoder/ms-marco-MiniLM-L6-v2",
    )
    return replace(meta, **overrides)  # type: ignore[arg-type]


def write(
    root: Path,
    name: str,
    records: list[EvalRecord],
    meta: RunMeta | None = None,
) -> Path:
    """Write one run directory and return it."""
    from eurohistory_rag.eval.record import write_run

    return write_run(meta or make_meta(name), records, root)


@pytest.fixture
def two_records() -> list[EvalRecord]:
    """A two-question run: one answered, one correctly refused."""
    return [
        make_record(question_id="q1"),
        make_record(question_id="q2", expected=[], answer=REFUSAL),
    ]


def test_identical_runs_pass(tmp_path: Path, two_records: list[EvalRecord]) -> None:
    """The no-op case, which is the one the gate must never fail.

    Rank is deterministic in this system across 1,200 measured chunk slots, so
    a gate that cannot pass two identical runs would fail every honest phase.
    """
    before = write(tmp_path, "before", two_records)
    after = write(tmp_path, "after", two_records, make_meta("after"))

    verdict = gate(before, after)

    assert verdict.comparable
    assert verdict.passed
    assert verdict.failures == []


def test_a_lost_result_fails_recall(tmp_path: Path) -> None:
    """The alarm rings: a question that used to hit now misses.

    The answer key is identical in both runs and what came back is not, which
    is the only shape a real regression can have -- an edited key is caught
    earlier, as a change to the conditions of the run.

    Written as a test because a gate that has never been observed to fail is
    a gate that has been observed to do nothing -- which is exactly what Phase
    8's dead reranker was, passing 337 tests.
    """
    before = write(tmp_path, "before", [make_record(doc_ids=["1:0", "2:0"])])
    after = write(
        tmp_path,
        "after",
        [make_record(doc_ids=["8:0", "9:0"])],
        make_meta("after"),
    )

    verdict = gate(before, after)

    assert not verdict.passed
    assert any("recall@5" in check.name for check in verdict.failures)


def test_an_undeclared_difference_stops_before_any_metric(tmp_path: Path) -> None:
    """A different collection is not a worse run, it is a different question."""
    before = write(tmp_path, "before", [make_record()])
    after = write(tmp_path, "after", [make_record()], make_meta("after", points=30362))

    verdict = gate(before, after)

    assert not verdict.comparable
    assert [check.name for check in verdict.failures] == ["points"]
    assert all(check.section == "comparability" for check in verdict.checks)


def test_a_declared_difference_warns_and_lets_the_metrics_run(tmp_path: Path) -> None:
    """Declaring the one thing you changed is how a real phase uses this."""
    before = write(tmp_path, "before", [make_record()])
    after = write(tmp_path, "after", [make_record()], make_meta("after", reranker=""))

    verdict = gate(before, after, changed=frozenset({"reranker"}))

    assert verdict.comparable
    assert verdict.passed
    assert any(check.status == "warn" for check in verdict.checks)
    assert any(check.section == "retrieval" for check in verdict.checks)


def test_declaring_a_change_that_did_not_happen_fails(tmp_path: Path) -> None:
    """Phase 8's dead switch, as a check.

    The run was presented as a reranked measurement, the flag was still false,
    and every number in it was real and meaningless. Saying a field changed
    when the two runs agree on it is that failure's exact signature.
    """
    before = write(tmp_path, "before", [make_record()])
    after = write(tmp_path, "after", [make_record()], make_meta("after"))

    verdict = gate(before, after, changed=frozenset({"reranker"}))

    assert not verdict.comparable
    assert [check.name for check in verdict.failures] == ["reranker"]


def test_two_real_changes_warn_about_the_one_change_rule(tmp_path: Path) -> None:
    """Two changes at once and the measurement cannot be attributed to either."""
    before = write(tmp_path, "before", [make_record()])
    after = write(
        tmp_path,
        "after",
        [make_record()],
        make_meta("after", reranker="", k=8),
    )

    verdict = gate(before, after, changed=frozenset({"reranker", "k"}))

    assert verdict.comparable
    assert any(check.name == "one change at a time" for check in verdict.checks)


def test_an_edited_answer_key_is_caught_as_a_question_set_change(
    tmp_path: Path,
) -> None:
    """Broadening a key raises recall without the system doing anything.

    Phase 15 measured 12.5 points of recall@5 that were the answer key rather
    than retrieval, so the key is compared as a condition of the run.
    """
    before = write(tmp_path, "before", [make_record(expected=["1:0"])])
    after = write(
        tmp_path,
        "after",
        [make_record(expected=["1:0", "2:0"])],
        make_meta("after"),
    )

    verdict = gate(before, after)

    assert not verdict.comparable
    assert [check.name for check in verdict.failures] == ["questions"]


def test_a_changed_refusal_fails(tmp_path: Path, two_records: list[EvalRecord]) -> None:
    """Refusals have zero measured variance, so any movement is real."""
    answered = [two_records[0], replace(two_records[1], answer=ANSWER)]
    before = write(tmp_path, "before", two_records)
    after = write(tmp_path, "after", answered, make_meta("after"))

    verdict = gate(before, after)

    assert not verdict.passed
    assert any("refusals" in check.name for check in verdict.failures)


def test_latency_is_reported_and_never_fails(tmp_path: Path) -> None:
    """Latency is not a property of this code, so it cannot gate this build.

    Three runs of Phase 16 that changed nothing at all moved a suite's p50 by
    893 ms, and nearly all of a query's time is the model vendor's. A gate on it
    would have failed two builds that were identical to their baseline.
    """
    before = write(tmp_path, "before", [make_record(total_ms=4000.0)])
    slower = write(
        tmp_path, "slower", [make_record(total_ms=40000.0)], make_meta("slower")
    )

    verdict = gate(before, slower)
    latency = [check for check in verdict.checks if check.section == "latency"]

    assert verdict.passed
    assert latency
    assert all(check.status == "report" for check in latency)


def test_top_score_ignores_the_fourth_decimal(tmp_path: Path) -> None:
    """The embedding API is not bit-exact; 35 of 1,200 slots moved by 0.0006."""
    before = write(tmp_path, "before", [make_record(top_score=0.7135)])
    after = write(
        tmp_path,
        "after",
        [make_record(top_score=0.7135 - TOP_SCORE_FLOOR / 2)],
        make_meta("after"),
    )

    assert gate(before, after).passed


def test_faithfulness_is_reported_and_never_fails(
    tmp_path: Path, two_records: list[EvalRecord]
) -> None:
    """A quarter of this metric's movement is the judge changing its mind.

    So a candidate whose unsupported claims went from none to one still passes,
    and the number is printed with its noise floor next to it.
    """
    before = write(tmp_path, "before", two_records)
    after = write(tmp_path, "after", two_records, make_meta("after"))
    judge_module.write(before, [Judgement("q1", "fake", [Claim("a", True, "ok")], 1.0)])
    judge_module.write(after, [Judgement("q1", "fake", [Claim("a", False, "no")], 0.0)])

    verdict = gate(before, after)

    generation = [check for check in verdict.checks if check.section == "generation"]
    assert verdict.passed
    assert generation
    assert all(check.status == "report" for check in generation)


def test_an_unjudged_run_simply_has_no_generation_section(
    tmp_path: Path, two_records: list[EvalRecord]
) -> None:
    """Judging costs money and happens later, so the gate must not require it."""
    before = write(tmp_path, "before", two_records)
    after = write(tmp_path, "after", two_records, make_meta("after"))

    verdict = gate(before, after)

    assert not [check for check in verdict.checks if check.section == "generation"]


def test_read_meta_ignores_fields_it_does_not_know(tmp_path: Path) -> None:
    """A run written by a later version must still be readable by this one."""
    directory = write(tmp_path, "run", [make_record()])
    path = directory / "meta.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace("{", '{"future_knob": 1,', 1),
        encoding="utf-8",
    )

    assert read_meta(directory).points == 54903


def test_render_says_which_way_the_gate_went(
    tmp_path: Path, two_records: list[EvalRecord]
) -> None:
    """The output is read by a person, so the verdict has to be in words."""
    before = write(tmp_path, "before", two_records)
    after = write(tmp_path, "after", two_records, make_meta("after"))

    assert "GATE PASSED" in render(gate(before, after), "before", "after")
