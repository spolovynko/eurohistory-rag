"""The instrument check: the shipped probe file, and what a failing probe says."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from eurohistory_rag.eval.probes import (
    PROBES_PATH,
    Probe,
    load_probes,
    render,
    run_probes,
)
from tests.fakes import ScriptedGenerator


def test_the_shipped_probe_file_loads() -> None:
    """The file itself is the test.

    A probe set that will not parse is discovered when someone runs a paid
    judge command, not here, unless something asserts it now.
    """
    probes = load_probes(PROBES_PATH)
    assert len(probes) >= 4
    assert {probe.expect for probe in probes} == {True, False}


def test_the_shipped_probes_include_the_phase_6_defect() -> None:
    """The reparations misattribution is the reason this metric exists.

    If it is ever removed the judge can be swapped for a word-overlap detector
    and every probe would still pass.
    """
    ids = {probe.id for probe in load_probes(PROBES_PATH)}
    assert "brest-reparations-attribution" in ids


def test_a_one_sided_probe_set_is_rejected(tmp_path: Path) -> None:
    """A judge that answers SUPPORTED to everything must not pass."""
    path = tmp_path / "probes.toml"
    path.write_text(
        '[[probe]]\nid = "a"\nclaim = "x"\nsources = "y"\nexpect = true\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="both supported and unsupported"):
        load_probes(path)


def make_probe(probe_id: str = "p", expect: bool = False) -> Probe:
    """One probe."""
    return Probe(
        id=probe_id, claim="Russia paid.", sources="agreed to pay", expect=expect
    )


def test_a_probe_passes_when_the_judge_agrees() -> None:
    results = run_probes(
        [make_probe(expect=False)], ScriptedGenerator(["NOT SUPPORTED - agreed only"])
    )
    assert results[0].passed


def test_a_probe_fails_when_the_judge_is_lenient() -> None:
    results = run_probes(
        [make_probe(expect=False)],
        ScriptedGenerator(["SUPPORTED - it says six billion"]),
    )
    assert not results[0].passed


def test_an_unparseable_verdict_fails_the_probe() -> None:
    results = run_probes([make_probe(expect=True)], ScriptedGenerator(["maybe"]))
    assert results[0].got is None
    assert not results[0].passed


def test_render_shows_the_claim_and_what_the_judge_said() -> None:
    results = run_probes(
        [make_probe("brest-reparations", expect=False)],
        ScriptedGenerator(["SUPPORTED - six billion marks appears"]),
    )
    text = render(results)
    assert "0/1 probes passed" in text
    assert "Russia paid." in text
    assert "six billion marks appears" in text
