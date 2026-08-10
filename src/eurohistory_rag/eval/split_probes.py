"""Testing the *first* half of the judge.

`probes.py` puts a claim to the verdict judge and checks the verdict. It cannot
see `extract_claims`, because it hands the judge a claim already split -- so a
splitter that mangles a sentence produces a fragment the verdict judge then
correctly fails, and the answer is reported unfaithful when the system did
nothing wrong.

That is not hypothetical. `stasi-scale` is flagged in all three D-088 runs, the
most trustworthy profile in this repository, and it is a false positive: the
splitter dropped "91,015 people full-time, including" and the judge failed the
fragment. Two stages, two places to be wrong, and until this module only the
second one was probed.

A separate module from `probes.py` rather than a second file format inside it:
one module, one reason to change. D-102.
"""

import logging
import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eurohistory_rag.eval.judge import extract_claims
from eurohistory_rag.generation.client import Generator

logger = logging.getLogger(__name__)

SPLITS_PATH = Path("eval/splits.toml")


class Conditional(BaseModel):
    """Any claim matching `when` must also match `then`.

    A conditional rather than a plain substring because that is the shape the
    defect actually has: the problem is never that "2,000" is absent, it is that
    "2,000" arrives without "including". Requiring both as separate substrings
    would pass a split that put them in different claims, which is the very
    thing being tested for.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    when: str = Field(min_length=1)
    then: str = Field(min_length=1)


class SplitProbe(BaseModel):
    """One answer whose correct split is written down by hand."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    rule: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    require: tuple[Conditional, ...] = ()
    forbid: tuple[str, ...] = ()
    min_claims: int = 1
    expect_none: bool = False
    why: str = ""

    @model_validator(mode="after")
    def _a_probe_must_check_something(self) -> "SplitProbe":
        """A probe with no checks passes whatever the splitter does."""
        if not (self.require or self.forbid or self.expect_none):
            raise ValueError(f"{self.id}: probe asserts nothing")
        return self


class _SplitFile(BaseModel):
    """The file as a whole."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    probe: tuple[SplitProbe, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _a_refusal_probe_is_present(self) -> "_SplitFile":
        """A set where every probe expects claims cannot catch a stuck splitter.

        A splitter that echoed its input back verbatim would satisfy every
        `require` in this file. The refusal probe -- which must yield nothing --
        is the only one it cannot.
        """
        if not any(probe.expect_none for probe in self.probe):
            raise ValueError("probes must include one that expects no claims")
        return self


def load_split_probes(path: Path = SPLITS_PATH) -> tuple[SplitProbe, ...]:
    """Parse eval/splits.toml, in file order."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    probes = _SplitFile.model_validate(raw).probe
    logger.info("split probes: %s, %d loaded", path, len(probes))
    return probes


@dataclass(frozen=True, slots=True)
class SplitResult:
    """What the splitter produced for one probe, and what was wrong with it."""

    probe: SplitProbe
    claims: list[str]
    failures: list[str]

    @property
    def passed(self) -> bool:
        """Did the split honour every rule this probe was written for?"""
        return not self.failures


def check(probe: SplitProbe, claims: Sequence[str]) -> list[str]:
    """Every way this split broke its probe, in words.

    Returns the reasons rather than a boolean, because a probe that says only
    "failed" leaves the reader doing by hand exactly the work this module exists
    to remove.
    """
    failures = []
    if probe.expect_none:
        return [f"expected no claims, got {len(claims)}"] if claims else []

    if len(claims) < probe.min_claims:
        failures.append(
            f"expected at least {probe.min_claims} claims, got {len(claims)}"
        )

    for rule in probe.require:
        for claim in claims:
            if re.search(rule.when, claim) and not re.search(rule.then, claim):
                failures.append(
                    f"claim matches /{rule.when}/ but drops /{rule.then}/: {claim!r}"
                )

    for pattern in probe.forbid:
        for claim in claims:
            if re.search(pattern, claim):
                failures.append(f"claim matches forbidden /{pattern}/: {claim!r}")

    return failures


def run_split_probes(
    probes: Sequence[SplitProbe], generator: Generator
) -> list[SplitResult]:
    """Put every probe through the splitter's real code path.

    `extract_claims` rather than a copy of it, for the reason `run_probes` calls
    `judge_claim`: a probe exercising its own reimplementation would certify
    something the eval never runs.
    """
    results = []
    for probe in probes:
        claims = extract_claims(probe.answer, generator)
        results.append(SplitResult(probe, claims, check(probe, claims)))
    return results


def render(results: Sequence[SplitResult]) -> str:
    """The probe table, with the offending claims quoted in full."""
    passed = sum(result.passed for result in results)
    lines = [f"{passed}/{len(results)} split probes passed", ""]
    for result in results:
        mark = "ok  " if result.passed else "FAIL"
        lines.append(f"{mark} {result.probe.id:<34} {result.probe.rule}")
        for failure in result.failures:
            lines.append(f"       {failure}")
        if not result.passed:
            lines.append(f"       why it matters: {result.probe.why.strip()}")
            lines += [f"       got: {claim}" for claim in result.claims]
    return "\n".join(lines) + "\n"
