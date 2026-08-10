"""Tests for the price shown before the money is spent.

The number does not have to be exact -- it is a warning, not an invoice. What
it has to be is *measured from something*, and honest about which something.
"""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from eurohistory_rag.eval.cost import FALLBACK_TOKENS, PRICES, dollars, estimate
from eurohistory_rag.eval.record import EvalRecord


def record(
    model: str, prompt: int, completion: int, cached: int | None = None
) -> EvalRecord:
    return EvalRecord(
        question_id="q1",
        question="why?",
        kind="easy",
        expected_doc_ids=["1:0"],
        retrieved=[],
        answer="Because [1].",
        generation_model=model,
        sources_sent=5,
        markers_found=[1],
        citations=[],
        search_ms=100.0,
        generate_ms=2000.0,
        total_ms=2100.0,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
    )


def write_run(root: Path, run_id: str, records: list[EvalRecord]) -> Path:
    directory = root / run_id
    directory.mkdir(parents=True)
    (directory / "records.jsonl").write_text(
        "\n".join(json.dumps(asdict(r)) for r in records) + "\n", encoding="utf-8"
    )
    return directory


def test_the_estimate_is_measured_from_the_last_run_of_that_model(
    tmp_path: Path,
) -> None:
    """Sixty questions at the Phase 16 token counts come to about eight cents.

    The arithmetic, spelled out: 2,620 prompt tokens at $0.40 per million plus
    182 completion tokens at $1.60, sixty times over.
    """
    write_run(tmp_path, "2026-08-06T1832Z", [record("gpt-4.1-mini", 2620, 182)])

    quote = estimate("gpt-4.1-mini", 60, tmp_path)

    assert 0.075 <= quote.dollars <= 0.085
    assert "measured" in quote.basis
    assert quote.questions == 60


def test_a_model_with_no_run_on_disk_says_so(tmp_path: Path) -> None:
    """An estimate whose basis is invisible is one nobody can sanity-check."""
    quote = estimate("gpt-4.1-nano", 60, tmp_path)

    assert "no previous" in quote.basis
    assert quote.dollars > 0


def test_the_newest_run_of_that_model_wins(tmp_path: Path) -> None:
    """Prices change with prompts, so the most recent measurement is the one."""
    write_run(tmp_path, "2026-01-01T0000Z", [record("gpt-4.1-mini", 10_000, 1_000)])
    write_run(tmp_path, "2026-08-06T1832Z", [record("gpt-4.1-mini", 2_620, 182)])

    assert estimate("gpt-4.1-mini", 60, tmp_path).dollars < 0.1


def test_another_models_run_is_not_borrowed(tmp_path: Path) -> None:
    """Token counts are not transferable between models.

    The prompt is the same size, but a model that reasons before answering
    spends several times the completion tokens of one that does not -- so a
    nano run cannot price a 4.1 run.
    """
    write_run(tmp_path, "2026-08-06T1832Z", [record("gpt-4.1-nano", 2620, 182)])

    quote = estimate("gpt-4.1", 60, tmp_path)

    assert "no previous" in quote.basis


def test_a_dearer_model_quotes_a_dearer_run(tmp_path: Path) -> None:
    """The picker changes the price, which is the point of showing it."""
    cheap = estimate("gpt-4.1-nano", 60, tmp_path)
    dear = estimate("gpt-4.1", 60, tmp_path)

    assert dear.dollars > cheap.dollars * 5


def test_every_selectable_model_has_a_price() -> None:
    """A model on the menu with no price would quote the wrong number silently.

    The allow-list and this table are two places holding one fact, so the day
    a fifth model is added this is the test that notices.
    """
    from eurohistory_rag.core.config import Settings

    assert set(Settings.model_fields["selectable_models"].default) <= set(PRICES)


def test_the_fallback_is_the_phase_16_measurement() -> None:
    """Documented rather than invented: it came off three sixty-question runs.

    The cached figure is 0 deliberately -- with no run on disk there is no
    evidence of a cache hit, and assuming one would under-warn before a spend.
    """
    assert FALLBACK_TOKENS == (2620.0, 182.0, 0.0)


def test_cached_tokens_are_billed_at_the_cached_rate(tmp_path: Path) -> None:
    """The whole point of the middle column: a cached token costs a quarter.

    2,000 fresh prompt tokens at $0.40 per million, 600 cached at $0.10, and 100
    completion at $1.60 -- spelled out because the arithmetic is the assertion.
    """
    spend = dollars(2600, 600, 100, "gpt-4.1-mini")

    assert spend == pytest.approx((2000 * 0.40 + 600 * 0.10 + 100 * 1.60) / 1_000_000)


def test_cached_tokens_are_a_subset_of_the_prompt_not_an_addition() -> None:
    """A run whose whole prompt was cached must cost less, never more.

    Phase 29's defect was the opposite reading -- every token charged at the full
    rate -- and the failure mode of over-correcting is billing twice.
    """
    all_cached = dollars(2600, 2600, 0, "gpt-4.1-mini")
    none_cached = dollars(2600, 0, 0, "gpt-4.1-mini")

    assert all_cached == pytest.approx(none_cached / 4)


def test_a_measured_cache_share_lowers_the_estimate(tmp_path: Path) -> None:
    """The number shown before a spend follows the discount the last run got.

    Two runs of the same shape, one that cached most of its prompt and one that
    cached none, must not quote the same price. D-103.
    """
    write_run(
        tmp_path / "cold", "2026-08-10T1413Z", [record("gpt-4.1-mini", 2600, 160)]
    )
    write_run(
        tmp_path / "warm",
        "2026-08-10T1413Z",
        [record("gpt-4.1-mini", 2600, 160, cached=2000)],
    )

    cold = estimate("gpt-4.1-mini", 106, tmp_path / "cold")
    warm = estimate("gpt-4.1-mini", 106, tmp_path / "warm")

    assert warm.dollars < cold.dollars
    assert "77% of it cached" in warm.basis
