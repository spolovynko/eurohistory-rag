"""Testing the ruler before trusting it.

Phase 7 shipped a metric that reported 0% refusals while the system refused
correctly every time, because the phrase it matched on had been guessed rather
than read. Phase 8 loaded a reranker that scored two unrelated documents at an
identical 0.000, and no unit test could catch it -- a test asserts the ranking
came from the reranker, not that the reranker is any good. A four-line probe
found it in two minutes.

The faithfulness judge has exactly that shape: a component whose output is
plausible whether or not it works. So it gets the same treatment. Every probe
below is a claim whose verdict is already known, written against source text
copied verbatim out of this repository's own eval runs, and the judge has to
agree with all of them before its numbers mean anything.

Two probes matter more than the rest. `brest-reparations-attribution` and
`brest-compensation-agreed` are the real Phase 6 defect and its twin: a fact
that is genuinely in the sources, attached to the wrong document or to the
wrong verb. A judge that passes those is checking the qualifier. A judge that
calls them SUPPORTED is a word-overlap detector wearing a metric's clothes, and
it would have scored the two answers Phase 6 caught by hand as perfect.
"""

import logging
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eurohistory_rag.eval.judge import judge_claim
from eurohistory_rag.generation.client import Generator

logger = logging.getLogger(__name__)

PROBES_PATH = Path("eval/probes.toml")


class Probe(BaseModel):
    """One claim whose correct verdict is already known."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    claim: str = Field(min_length=1)
    sources: str = Field(min_length=1)
    expect: bool
    why: str = ""


class _ProbeFile(BaseModel):
    """The file as a whole."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    probe: tuple[Probe, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _both_verdicts_present(self) -> "_ProbeFile":
        """A probe set that only expects one verdict cannot detect a stuck judge.

        A judge that answers SUPPORTED to everything passes an all-supported
        set perfectly, which is the exact failure this file exists to catch.
        """
        if len({probe.expect for probe in self.probe}) < 2:
            raise ValueError("probes must include both supported and unsupported")
        return self


def load_probes(path: Path = PROBES_PATH) -> tuple[Probe, ...]:
    """Parse eval/probes.toml, in file order."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    probes = _ProbeFile.model_validate(raw).probe
    logger.info("probes: %s, %d loaded", path, len(probes))
    return probes


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What the judge said about one probe, and whether that was right."""

    probe: Probe
    got: bool | None
    reason: str

    @property
    def passed(self) -> bool:
        """Did the judge return the verdict this probe was written for?"""
        return self.got is self.probe.expect


def run_probes(probes: Sequence[Probe], generator: Generator) -> list[ProbeResult]:
    """Put every probe to the judge, using the judge's real code path.

    `judge_claim` rather than a copy of it: a probe that exercised its own
    reimplementation of the prompt would certify something the eval never runs.
    """
    results = []
    for probe in probes:
        claim = judge_claim(probe.claim, probe.sources, generator)
        results.append(
            ProbeResult(probe=probe, got=claim.supported, reason=claim.reason)
        )
    return results


def render(results: Sequence[ProbeResult]) -> str:
    """The probe table, failures spelled out."""
    passed = sum(result.passed for result in results)
    lines = [f"{passed}/{len(results)} probes passed", ""]
    for result in results:
        verdict = {True: "SUPPORTED", False: "NOT SUPPORTED", None: "UNPARSEABLE"}[
            result.got
        ]
        lines.append(
            f"{'ok  ' if result.passed else 'FAIL'} {result.probe.id:<34} got {verdict}"
        )
        if not result.passed:
            wanted = "SUPPORTED" if result.probe.expect else "NOT SUPPORTED"
            lines += [
                f"       claim:      {result.probe.claim}",
                f"       expected:   {wanted} -- {result.probe.why}",
                f"       judge said: {result.reason}",
            ]
    return "\n".join(lines) + "\n"
