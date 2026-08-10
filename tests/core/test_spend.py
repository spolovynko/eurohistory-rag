"""The ledger, the two ceilings, and the promise that a refusal costs nothing.

The load-bearing test in this file is `test_ceiling_refuses_before_any_call`.
Every other one checks arithmetic or bookkeeping; that one checks the claim the
whole phase is built on -- that a run over the limit is refused *before* the
first question, not billed and then reported. A ceiling enforced after the money
has left is a receipt, and this file is what stops that shipping. D-104.
"""

from pathlib import Path

import pytest

from eurohistory_rag.core.spend import (
    PRICES,
    CeilingExceeded,
    Ledger,
    Meter,
    check_run,
    dollars,
)


def _ledger(tmp_path: Path) -> Ledger:
    """A ledger over a temporary directory.

    Never the real one. A test that wrote to `data/spend/` would either inflate
    a real day's total or, worse, be refused by a ceiling somebody else had
    already reached -- a test that fails depending on how much you spent this
    morning is not a test.
    """
    return Ledger(tmp_path / "spend")


def test_dollars_charges_cached_tokens_at_the_cached_rate() -> None:
    """Cached prompt tokens are a subset of the prompt, billed cheaper."""
    full, cached, _ = PRICES["gpt-4.1-mini"]
    assert full > cached
    fresh_only = dollars(1000, 0, 0, "gpt-4.1-mini")
    half_cached = dollars(1000, 500, 0, "gpt-4.1-mini")
    assert half_cached < fresh_only
    assert half_cached == pytest.approx((500 * full + 500 * cached) / 1_000_000)


def test_dollars_never_charges_negative_for_impossible_counts() -> None:
    """More cached tokens than prompt tokens is nonsense, not a refund.

    The provider should never report it, but a price list that can go negative
    is a price list that can talk a ceiling into letting a run through.
    """
    assert dollars(100, 500, 0, "gpt-4.1-mini") > 0


def test_unknown_model_falls_back_rather_than_raising() -> None:
    """A model missing from the price list is estimated, not fatal.

    Deliberate: a new model id should produce a slightly wrong number, not a
    500 on every answer until someone edits a dict.
    """
    assert dollars(1000, 0, 100, "gpt-9-imaginary") == dollars(
        1000, 0, 100, "gpt-4.1-mini"
    )


def test_a_day_with_no_ledger_file_has_spent_nothing(tmp_path: Path) -> None:
    """Midnight is not an error state."""
    total = _ledger(tmp_path).today()
    assert total.dollars == 0.0
    assert total.calls == 0


def test_recorded_spend_adds_up_and_counts_calls(tmp_path: Path) -> None:
    """Two calls, two lines, one total."""
    ledger = _ledger(tmp_path)
    ledger.record(0.01, "gpt-4.1-mini")
    ledger.record(0.02, "gpt-4.1-mini")
    total = ledger.today()
    assert total.dollars == pytest.approx(0.03)
    assert total.calls == 2


def test_an_unreadable_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    """A half-written line from a killed process must not disarm the ceiling.

    Under-counting by one call is survivable. Refusing every answer until a
    person edits a file by hand is not, and that is what raising here would do.
    """
    ledger = _ledger(tmp_path)
    ledger.record(0.05, "gpt-4.1-mini")
    day_file = next((tmp_path / "spend").glob("*.jsonl"))
    with day_file.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    assert ledger.today().dollars == pytest.approx(0.05)


def test_an_unwritable_ledger_does_not_take_the_system_down(tmp_path: Path) -> None:
    """A ledger that cannot be written is logged, not raised.

    A full disk should not stop every answer in the system. The failure is loud
    in the log and the total under-counts, which is the lesser of the two harms.
    """
    blocked = tmp_path / "spend"
    blocked.write_text("I am a file where a directory should be", encoding="utf-8")
    Ledger(blocked).record(0.01, "gpt-4.1-mini")


def test_the_day_ceiling_allows_spend_below_it(tmp_path: Path) -> None:
    """Under the limit, nothing happens. This is the ordinary case."""
    ledger = _ledger(tmp_path)
    ledger.record(0.20, "gpt-4.1-mini")
    ledger.check_day(1.00)


def test_the_day_ceiling_refuses_at_the_limit(tmp_path: Path) -> None:
    """At the ceiling, not merely over it -- `>=`, and the message says why."""
    ledger = _ledger(tmp_path)
    ledger.record(1.00, "gpt-4.1-mini")
    with pytest.raises(CeilingExceeded, match="daily ceiling"):
        ledger.check_day(1.00)


def test_a_ceiling_of_zero_means_no_limit(tmp_path: Path) -> None:
    """So a machine that wants no ceiling says so in .env, not in code."""
    ledger = _ledger(tmp_path)
    ledger.record(99.0, "gpt-4.1-mini")
    ledger.check_day(0.0)


def test_the_run_ceiling_refuses_a_quote_over_it() -> None:
    """The quote shown next to the button is the figure that refuses the run."""
    check_run(0.14, 0.50)
    with pytest.raises(CeilingExceeded, match="per-run ceiling"):
        check_run(0.51, 0.50)


class CountingGenerator:
    """A generator that records how many times a model was actually reached.

    The whole point of this fake is the counter. Asserting that a refusal
    "raises" proves nothing about cost -- an exception raised after the request
    left is still an exception, and still a bill. Counting the calls is the only
    way to state the claim the phase is judged on.
    """

    def __init__(self, meter: Meter) -> None:
        self.calls = 0
        self._meter = meter

    def stream(self) -> str:
        """The shape of `OpenAIGenerator.stream`, minus the network.

        The check happens in the same place and the same order it does in the
        real client: before the request is built, not after it returns.
        """
        self._meter.check()
        self.calls += 1
        self._meter.record_tokens(1000, 0, 100, "gpt-4.1-mini", "gpt-4.1-mini")
        return "an answer"


def test_ceiling_refuses_before_any_call(tmp_path: Path) -> None:
    """The done-when of Phase 30, stated as a number: zero calls.

    The band written into D-104 before any code was: good is exactly 0 model
    calls on the refusal path, and the *impossible* result is a refusal that
    arrives after a call -- which would mean the ceiling is a receipt rather
    than a limit, and the phase has failed whatever else passes.
    """
    ledger = _ledger(tmp_path)
    ledger.record(1.00, "gpt-4.1-mini")
    generator = CountingGenerator(Meter(ledger=ledger, day_ceiling=1.00))

    with pytest.raises(CeilingExceeded):
        generator.stream()

    assert generator.calls == 0
    assert ledger.today().calls == 1  # only the spend that was there beforehand


def test_metering_a_call_moves_the_day_total(tmp_path: Path) -> None:
    """Under the ceiling the call goes through and the total moves."""
    ledger = _ledger(tmp_path)
    generator = CountingGenerator(Meter(ledger=ledger, day_ceiling=1.00))
    generator.stream()
    assert generator.calls == 1
    assert ledger.today().dollars == pytest.approx(
        dollars(1000, 0, 100, "gpt-4.1-mini")
    )


def test_a_call_with_no_token_counts_is_recorded_as_nothing(tmp_path: Path) -> None:
    """An unmeasured call is not guessed at.

    Same argument that keeps `cached_tokens` as `None` rather than `0` on the 27
    older runs: a ceiling enforced partly on measurements and partly on
    invention is a number nobody can act on. It under-counts, and it says so.
    """
    ledger = _ledger(tmp_path)
    meter = Meter(ledger=ledger, day_ceiling=1.00)
    meter.record_tokens(None, None, None, "gpt-4.1-mini", "gpt-4.1-mini")
    assert ledger.today().calls == 0
