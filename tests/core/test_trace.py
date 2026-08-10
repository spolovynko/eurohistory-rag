"""What a trace has to guarantee before anything is instrumented with it."""

import pytest

from eurohistory_rag.core.trace import Trace


def test_a_span_records_its_name_and_a_duration() -> None:
    trace = Trace()
    with trace.span("embed"):
        pass

    assert [span.name for span in trace.spans] == ["embed"]
    assert trace.spans[0].ms >= 0.0


def test_a_parent_precedes_its_children_and_sits_one_level_shallower() -> None:
    """The ordering the whole format rests on.

    Appended on the way in, so reading the list top to bottom is reading the
    tree. Built on the way out instead, `search` would follow the stages it
    contains and the indentation would describe nothing.
    """
    trace = Trace()
    with trace.span("search"):
        with trace.span("embed"):
            pass
        with trace.span("dense"):
            pass
    with trace.span("generate"):
        pass

    assert [(s.name, s.depth) for s in trace.spans] == [
        ("search", 0),
        ("embed", 1),
        ("dense", 1),
        ("generate", 0),
    ]


def test_children_never_outlast_their_parent() -> None:
    """D-101's first impossible check, on the one case that can be forced.

    Real timings are checked per question against a real run; this pins the
    arithmetic that makes that check meaningful at all.
    """
    trace = Trace()
    with trace.span("search"), trace.span("rerank"):
        time_sink = sum(range(200_000))
    assert time_sink >= 0

    parent, child = trace.spans
    assert child.ms <= parent.ms


def test_a_stage_that_raised_still_reports_its_time() -> None:
    """The failing stage is the one worth reading, so it is not dropped."""
    trace = Trace()
    with pytest.raises(RuntimeError), trace.span("generate"):
        raise RuntimeError("the model went away")

    assert [span.name for span in trace.spans] == ["generate"]
    assert trace.spans[0].ms >= 0.0


def test_depth_recovers_after_a_stage_raises_inside_a_parent() -> None:
    """A swallowed failure must not leave every later span indented forever."""
    trace = Trace()
    with trace.span("search"), pytest.raises(RuntimeError), trace.span("rerank"):
        raise RuntimeError("no model")
    with trace.span("generate"):
        pass

    assert [(s.name, s.depth) for s in trace.spans] == [
        ("search", 0),
        ("rerank", 1),
        ("generate", 0),
    ]


def test_a_stage_can_annotate_its_own_span() -> None:
    """The note is what makes a trace replayable rather than only countable."""
    trace = Trace()
    with trace.span("dense") as span:
        span.note = "20 candidates"

    assert trace.spans[0].note == "20 candidates"


def test_two_traces_do_not_share_a_list() -> None:
    """The eval runner asks 106 questions in a row through the same objects."""
    first, second = Trace(), Trace()
    with first.span("embed"):
        pass

    assert len(first.spans) == 1
    assert second.spans == []
