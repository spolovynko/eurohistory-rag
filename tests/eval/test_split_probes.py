"""The splitter probe's own scoring, checked without a model.

`split-probe` costs a few cents and needs a key. The rules it applies are pure
functions of a probe and a list of claims, so they are tested here for free --
and they have to be, because a probe that scores wrongly is the same class of
defect as the metric this phase was opened to fix. The `marshall-markers`
probe shipped asserting the wrong rule and failed a correct split; that is what
this file exists to catch next time. D-102.
"""

from collections.abc import Iterator, Sequence

import pytest
from pydantic import ValidationError

from eurohistory_rag.eval.judge import extract_claims
from eurohistory_rag.eval.split_probes import (
    SPLITS_PATH,
    Conditional,
    SplitProbe,
    check,
    load_split_probes,
    render,
    run_split_probes,
)
from eurohistory_rag.generation.client import Completion, EmptyCompletion
from eurohistory_rag.generation.messages import Message

# The recorded defect, as the splitter actually produced it in D-088.
STASI = SplitProbe(
    id="stasi",
    rule="a subset is not a total",
    answer="In 1989 it employed 91,015 full-time, including 2,000 collaborators.",
    require=(Conditional(when="2,?000", then="including|91,015"),),
)

BROKEN_SPLIT = ["In 1989, the Stasi employed 2,000 fully employed collaborators."]
GOOD_SPLIT = ["In 1989 it employed 91,015 full-time, including 2,000 collaborators."]


class EmptyGenerator:
    """A model that replies with nothing, the way it does on a refusal."""

    @property
    def model(self) -> str:
        """Named anyway, like the other fakes."""
        return "fake-splitter"

    def stream(self, messages: Sequence[Message]) -> Iterator[str | Completion]:
        """Fail the way the real client does on an empty reply."""
        raise EmptyCompletion("The model returned an empty answer.")
        yield  # pragma: no cover -- unreachable, and what makes this a generator


class OneReplyGenerator:
    """A model that always returns the same claim list."""

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def model(self) -> str:
        """The name recorded on every judgement."""
        return "fake-splitter"

    def stream(self, messages: Sequence[Message]) -> Iterator[str | Completion]:
        """Yield the canned split."""
        yield Completion(text=self._text)


def test_the_recorded_defect_is_caught() -> None:
    """The split that made `stasi-scale` a false positive in three runs."""
    failures = check(STASI, BROKEN_SPLIT)
    assert failures and "2,?000" in failures[0]


def test_a_split_that_keeps_the_qualifier_passes() -> None:
    assert check(STASI, GOOD_SPLIT) == []


def test_a_refusal_probe_fails_when_anything_comes_back() -> None:
    """The check that a stuck splitter cannot satisfy."""
    probe = SplitProbe(id="r", rule="refusals", answer="a", expect_none=True)
    assert check(probe, []) == []
    assert check(probe, ["The sources do not cover Seveso."]) == [
        "expected no claims, got 1"
    ]


def test_too_few_claims_is_reported() -> None:
    probe = SplitProbe(id="two", rule="split", answer="a", min_claims=2, forbid=("zz",))
    assert "expected at least 2 claims, got 1" in check(probe, ["one claim"])


def test_a_forbidden_pattern_is_reported() -> None:
    probe = SplitProbe(id="m", rule="markers", answer="a", forbid=(r"\[\d+\]",))
    assert check(probe, ["France received 18% [1]."])
    assert check(probe, ["France received 18%."]) == []


def test_a_probe_that_asserts_nothing_is_rejected() -> None:
    """A probe with no checks passes whatever the splitter does, so it is a bug."""
    with pytest.raises(ValidationError, match="asserts nothing"):
        SplitProbe(id="empty", rule="none", answer="a")


def test_a_probe_file_with_no_refusal_case_is_rejected() -> None:
    """Without it, a splitter that echoes its input back scores full marks."""
    from eurohistory_rag.eval.split_probes import _SplitFile

    with pytest.raises(ValidationError, match="expects no claims"):
        _SplitFile.model_validate(
            {"probe": [{"id": "a", "rule": "r", "answer": "x", "forbid": ["q"]}]}
        )


def test_the_shipped_probe_file_parses_and_covers_ten_rules() -> None:
    """The file on disk is loadable and every probe states a distinct rule."""
    probes = load_split_probes(SPLITS_PATH)
    assert len(probes) == 10
    assert len({probe.rule for probe in probes}) == 10
    assert all(probe.why.strip() for probe in probes)


def test_an_empty_reply_is_no_claims_rather_than_a_failure() -> None:
    """The bug the splitter fix exposed.

    `CLAIM_INSTRUCTIONS` ends "if the answer makes no factual claim, reply with
    nothing", and the client treated an empty reply as the model falling over --
    so the first correctly-split refusal crashed the probe run.
    """
    assert extract_claims("The sources do not cover Seveso.", EmptyGenerator()) == []


def test_a_probe_run_reports_the_claims_it_got() -> None:
    """A failure has to print the split, or the reader cannot see what broke."""
    results = run_split_probes([STASI], OneReplyGenerator(BROKEN_SPLIT[0]))
    assert not results[0].passed
    assert BROKEN_SPLIT[0] in render(results)
    assert "0/1 split probes passed" in render(results)
