"""The faithfulness judge: parsing, scoring, and what it refuses to score."""

from pathlib import Path

from eurohistory_rag.eval.judge import (
    Claim,
    Judgement,
    judge_all,
    judge_record,
    parse_claims,
    parse_verdict,
    read,
    render,
    score,
    sources_block,
    summarise,
    write,
)
from eurohistory_rag.eval.record import EvalRecord, Retrieved
from tests.fakes import ScriptedGenerator, UnavailableGenerator


def make_record(
    answer: str = "The treaty was signed in 1918.",
    sources_sent: int = 2,
    texts: tuple[str, ...] = ("Signed 3 March 1918.", "Russia lost Ukraine."),
    error: str | None = None,
) -> EvalRecord:
    """A record carrying only what the judge reads."""
    return EvalRecord(
        question_id="q",
        question="when was it signed?",
        kind="easy",
        expected_doc_ids=["1:0"],
        retrieved=[
            Retrieved(
                rank=rank,
                chunk_id=f"1:0:{rank}",
                doc_id="1:0",
                page_id=1,
                source="Treaty",
                score=0.7,
                text=text,
            )
            for rank, text in enumerate(texts, start=1)
        ],
        answer=answer,
        generation_model="fake",
        sources_sent=sources_sent,
        markers_found=[1],
        citations=[],
        search_ms=1.0,
        generate_ms=1.0,
        total_ms=2.0,
        error=error,
    )


def test_not_supported_is_read_before_supported() -> None:
    """The one parsing bug that would make the metric report a perfect score.

    "NOT SUPPORTED" contains "SUPPORTED", so a prefix check in the wrong order
    marks every failure as a pass and never raises.
    """
    assert parse_verdict("NOT SUPPORTED - the source says a later protocol")[0] is False
    assert parse_verdict("SUPPORTED - source 1 states it")[0] is True


def test_an_unreadable_verdict_is_neither() -> None:
    supported, reason = parse_verdict("I think probably yes")
    assert supported is None
    assert "probably" in reason


def test_parse_claims_strips_bullets_markers_and_noise() -> None:
    claims = parse_claims(
        "1. The treaty was signed in 1918 [2].\n- Russia lost land\nok"
    )
    assert claims == ["The treaty was signed in 1918 .", "Russia lost land"]


def test_parse_claims_caps_the_count() -> None:
    assert len(parse_claims("\n".join(f"claim number {i}" for i in range(30)))) == 12


def test_sources_block_holds_only_what_the_model_was_shown() -> None:
    record = make_record(sources_sent=1)
    block = sources_block(record)
    assert "Signed 3 March 1918." in block
    assert "Russia lost Ukraine." not in block


def test_score_ignores_claims_the_judge_could_not_answer() -> None:
    claims = [
        Claim("a", True, ""),
        Claim("b", False, ""),
        Claim("c", None, ""),
    ]
    assert score(claims) == 0.5


def test_score_is_none_when_nothing_could_be_judged() -> None:
    assert score([Claim("a", None, "")]) is None


def test_a_refusal_is_skipped_rather_than_scored() -> None:
    """Refusing correctly is the system working, not an unfaithful answer."""
    judgement = judge_record(
        make_record(answer="Not in the sources."), ScriptedGenerator([])
    )
    assert judgement.faithfulness is None
    assert judgement.skipped == "refusal"


def test_a_generation_error_is_skipped() -> None:
    judgement = judge_record(
        make_record(error="connection refused"), ScriptedGenerator([])
    )
    assert judgement.skipped == "generation error"


def test_a_judge_failure_is_recorded_not_raised() -> None:
    judgement = judge_record(make_record(), UnavailableGenerator())
    assert judgement.faithfulness is None
    assert judgement.skipped.startswith("judge failed")


def test_judging_one_answer_end_to_end() -> None:
    generator = ScriptedGenerator(
        [
            "The treaty was signed in 1918.\nRussia paid six billion marks.",
            "SUPPORTED - source 1 gives the date",
            "NOT SUPPORTED - a later protocol required it, not the treaty",
        ]
    )
    judgement = judge_record(make_record(), generator)

    assert judgement.faithfulness == 0.5
    assert [claim.supported for claim in judgement.claims] == [True, False]
    assert judgement.judge_model == "fake-judge"


def test_one_call_per_claim() -> None:
    """The design that removes verbosity and position bias, asserted.

    One extraction call plus one call per claim. Judging every claim in a
    single call would let a confident neighbour carry a weak one.
    """
    generator = ScriptedGenerator(
        ["claim one here\nclaim two here", "SUPPORTED - yes", "SUPPORTED - yes"]
    )
    judge_record(make_record(), generator)
    assert len(generator.calls) == 3


def test_summary_counts_answers_and_claims_separately() -> None:
    judgements = [
        Judgement("a", "m", [Claim("x", True, ""), Claim("y", False, "")], 0.5),
        Judgement("b", "m", [Claim("z", True, "")], 1.0),
        Judgement("c", "m", [], None, skipped="refusal"),
    ]
    summary = summarise(judgements)

    assert (summary.answers_judged, summary.answers_skipped) == (2, 1)
    assert (summary.supported, summary.unsupported) == (2, 1)
    assert summary.mean_faithfulness == 0.75
    assert summary.fully_faithful_answers == 1


def test_render_prints_the_unsupported_claims() -> None:
    judgements = [Judgement("a", "m", [Claim("Russia paid.", False, "agreed to")], 0.0)]
    text = render(judgements, summarise(judgements))
    assert "Russia paid." in text
    assert "agreed to" in text


def test_judgements_round_trip(tmp_path: Path) -> None:
    judgements = [Judgement("a", "m", [Claim("x", None, "odd reply")], None)]
    write(tmp_path, judgements)
    assert read(tmp_path) == judgements


def test_judge_all_visits_every_record() -> None:
    records = [make_record(answer="Not in the sources.") for _ in range(3)]
    assert len(judge_all(records, ScriptedGenerator([]))) == 3
