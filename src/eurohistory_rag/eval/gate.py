"""Does this run count as a regression against the last one?

Seven measured phases have had nothing between a silent regression and the
finished system except a person opening `summary.txt` and noticing. Twice that
nearly failed, and neither near-miss was a metric moving:

- Phase 8 shipped a run with the reranker flag still false. Every number was
  real, the run measured nothing, and it was caught by a metadata field added
  twenty minutes earlier.
- Phase 14 came one command away from re-fetching articles under a new theme,
  which would have shifted section positions so every ground-truth `doc_id`
  named a different section -- with the eval still cheerfully printing numbers.

Both are the same failure: a run that is **not comparable** to the one before it
while looking exactly like one that is. So this module checks comparability
first and refuses to print a single metric until it holds.

The thresholds are not invented here. They are the D-088 decision rule, measured
over three identical runs, and the split they impose is the whole design:
retrieval and refusals are deterministic and gate the build, while every
generation number wobbles on its own and can only be reported. A gate that
failed a build on an unsupported-claim count would fire on nothing about a third
of the time, because a quarter of that count's movement is the judge disagreeing
with itself.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal

from eurohistory_rag.eval import judge as judge_module
from eurohistory_rag.eval.metrics import Summary, refused, summarise
from eurohistory_rag.eval.record import EvalRecord, RunMeta, read_records

# Every field of meta.json that changes what a number means. A difference in any
# of these makes the two runs incomparable unless it is declared on the command
# line, and `note`, `run_id`, `started_at` and `git_sha` are deliberately absent:
# they describe the run, they do not change its results.
COMPARABILITY_FIELDS = (
    "embedding_model",
    "generation_model",
    "collection",
    "points",
    "k",
    "max_per_document",
    "overfetch",
    "reranker",
    "hybrid",
    "verifier",
    "temporal",
)

# The question set is compared as a field alongside the others, because a
# question added or an answer key edited moves every aggregate in the table for
# a reason that has nothing to do with the system.
QUESTIONS_FIELD = "questions"

# D-088's minimum detectable effects. Retrieval and refusals gate; nothing below
# the second block ever fails a build.
TOP_SCORE_FLOOR = 0.001

# Latency is reported, not gated, and the number below is why. Phase 8 put the
# floor at 600 ms, measured on the whole-run p50 of thirty questions. Re-measured
# here on the three identical runs of Phase 16, the spread is 315 ms across all
# sixty questions and **893 ms within a thirty-question suite** -- a p50 of
# thirty values is the fifteenth of them, and one question crossing the middle
# drags it. Nearly all of it is generation, which is the model vendor's load on
# the day rather than anything in this repository. Gating on it would have failed
# a build on two runs that changed nothing.
LATENCY_NOISE_MS = 900.0

# Time to first token has no measured noise floor -- Phase 16's three identical
# runs predate the field. This borrows the total-latency spread rather than
# inventing a number, and says so: it is the same clock measuring a shorter
# interval, so it is if anything too wide. Reported, never gated, like the line
# above it. D-095.
TTFT_NOISE_MS = LATENCY_NOISE_MS

UNSUPPORTED_FLOOR = 4
FAITHFULNESS_FLOOR = 0.007
FULLY_FAITHFUL_FLOOR = 2
CLAIMS_FLOOR = 35

# Floating point: two runs scored by the same code from the same records produce
# bit-identical means, but a comparison written as `>` on floats is one refactor
# away from failing a build on the fifteenth decimal.
EPSILON = 1e-9

Status = Literal["pass", "fail", "warn", "report"]


@dataclass(frozen=True, slots=True)
class Check:
    """One comparison, and what it means.

    Carries the rule it was judged against rather than only the verdict: a
    failed gate has to say *why* 0.729 is a failure and 0.750 is not, or the
    next person widens the threshold until the build goes green.
    """

    section: str
    name: str
    baseline: str
    candidate: str
    rule: str
    status: Status


@dataclass(frozen=True, slots=True)
class Verdict:
    """Every check that ran, and whether the gate lets this through."""

    comparable: bool
    checks: list[Check]

    @property
    def failures(self) -> list[Check]:
        """The checks that failed, in the order they ran."""
        return [check for check in self.checks if check.status == "fail"]

    @property
    def passed(self) -> bool:
        """True when nothing failed. This is what the exit code is built on."""
        return not self.failures


def read_meta(directory: Path) -> RunMeta:
    """Load a run's conditions from its meta.json.

    Fields added after a run was written fall back to their defaults, which is
    what makes a Phase 7 run comparable to a Phase 17 one at all.
    """
    raw = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    known = {field.name for field in fields(RunMeta)}
    return RunMeta(**{key: value for key, value in raw.items() if key in known})


def question_set(records: Sequence[EvalRecord]) -> dict[str, tuple[str, ...]]:
    """Each question's id mapped to the answer key it was scored against.

    Both halves matter. A question added moves every aggregate; an answer key
    edited moves recall without anything about the system changing, and Phase 15
    measured that as 12.5 points of recall@5 on questions that were answering
    correctly.
    """
    return {
        record.question_id: tuple(sorted(record.expected_doc_ids)) for record in records
    }


def _describe(keys: dict[str, tuple[str, ...]]) -> str:
    """A question set as a short string, for the difference column."""
    return f"{len(keys)}q/{sum(len(v) for v in keys.values())}keys"


def _fmt(value: float | None, digits: int = 3) -> str:
    """A number for the table, or n/a where the metric does not apply."""
    return "n/a" if value is None else f"{value:.{digits}f}"


def _no_drop(
    section: str,
    name: str,
    baseline: float | None,
    candidate: float | None,
    floor: float = 0.0,
    digits: int = 3,
) -> Check:
    """A metric where lower is worse."""
    rule = "no drop" if floor == 0.0 else f"drop <= {floor:g}"
    if baseline is None or candidate is None:
        shape: Status = "pass" if baseline == candidate else "fail"
        return Check(section, name, _fmt(baseline), _fmt(candidate), rule, shape)
    status: Status = "fail" if baseline - candidate > floor + EPSILON else "pass"
    return Check(
        section, name, _fmt(baseline, digits), _fmt(candidate, digits), rule, status
    )


def _no_rise(
    section: str,
    name: str,
    baseline: float,
    candidate: float,
    floor: float = 0.0,
    digits: int = 0,
) -> Check:
    """A metric where higher is worse."""
    rule = "no rise" if floor == 0.0 else f"rise <= {floor:g}"
    status: Status = "fail" if candidate - baseline > floor + EPSILON else "pass"
    return Check(
        section, name, _fmt(baseline, digits), _fmt(candidate, digits), rule, status
    )


def _no_change(section: str, name: str, baseline: int, candidate: int) -> Check:
    """A metric where any movement at all is a finding.

    Refusals are the only generation behaviour in this system with zero measured
    variance -- 7, 7, 7 across three runs and three definitions of the word --
    which is what makes them readable at single-question resolution.
    """
    status: Status = "pass" if baseline == candidate else "fail"
    return Check(section, name, str(baseline), str(candidate), "no change", status)


def check_comparability(
    baseline: RunMeta,
    candidate: RunMeta,
    baseline_records: Sequence[EvalRecord],
    candidate_records: Sequence[EvalRecord],
    changed: frozenset[str] = frozenset(),
) -> list[Check]:
    """Are these two runs measuring the same thing under the same conditions?

    Anything that differs must be named in `changed`, and -- the other half,
    and the one Phase 8 needed -- anything named in `changed` must actually
    differ. Declaring a change that did not happen is exactly the dead-switch
    signature: a run presented as a measurement that measured nothing.
    """
    differences: dict[str, tuple[str, str]] = {
        field: (str(getattr(baseline, field)), str(getattr(candidate, field)))
        for field in COMPARABILITY_FIELDS
        if getattr(baseline, field) != getattr(candidate, field)
    }
    before, after = question_set(baseline_records), question_set(candidate_records)
    if before != after:
        differences[QUESTIONS_FIELD] = (_describe(before), _describe(after))

    checks = []
    for field, (was, now) in sorted(differences.items()):
        declared = field in changed
        checks.append(
            Check(
                "comparability",
                field,
                was,
                now,
                "declared" if declared else "must be identical",
                "warn" if declared else "fail",
            )
        )
    for field in sorted(changed - set(differences)):
        checks.append(
            Check(
                "comparability",
                field,
                "identical",
                "identical",
                "declared changed, and is not",
                "fail",
            )
        )

    real = sorted(field for field in changed if field in differences)
    if len(real) > 1:
        checks.append(
            Check(
                "comparability",
                "one change at a time",
                "1",
                str(len(real)),
                ", ".join(real),
                "warn",
            )
        )
    if not checks:
        fields = len(COMPARABILITY_FIELDS) + 1
        checks.append(
            Check(
                "comparability",
                f"all {fields} fields",
                "identical",
                "identical",
                "must be identical",
                "pass",
            )
        )
    return checks


def _suites(records: Sequence[EvalRecord]) -> list[str]:
    """Every question batch in a run, plus the combined row.

    Per suite rather than only the total, because the total can only report an
    average: Phase 14 grew the corpus 81% and every headline number stayed put,
    and the reason was visible only once the batches were separated.
    """
    return [*sorted({record.suite for record in records}), "all"]


def _subset(records: Sequence[EvalRecord], suite: str) -> list[EvalRecord]:
    """The records belonging to one suite, or all of them."""
    if suite == "all":
        return list(records)
    return [record for record in records if record.suite == suite]


def _retrieval_checks(suite: str, before: Summary, after: Summary) -> list[Check]:
    """The rank-based metrics, which are deterministic and therefore gate."""
    return [
        _no_drop(
            "retrieval", f"{suite} recall@5", before.recall_at_5, after.recall_at_5
        ),
        _no_drop(
            "retrieval", f"{suite} recall@20", before.recall_at_20, after.recall_at_20
        ),
        _no_drop(
            "retrieval",
            f"{suite} coverage@5",
            before.coverage_at_5,
            after.coverage_at_5,
        ),
        _no_drop("retrieval", f"{suite} MRR", before.mrr, after.mrr),
        # Not a rank metric, and it gates for the same reason they do: it is
        # computed by string comparison against a key written before the run, so
        # it cannot drift the way a judged number can. D-097.
        _no_drop("retrieval", f"{suite} fact rate", before.fact_rate, after.fact_rate),
        _no_drop(
            "retrieval",
            f"{suite} top-1 score",
            before.mean_top_score,
            after.mean_top_score,
            TOP_SCORE_FLOOR,
        ),
    ]


def _behaviour_checks(
    suite: str,
    before: Summary,
    after: Summary,
    before_records: Sequence[EvalRecord],
    after_records: Sequence[EvalRecord],
) -> list[Check]:
    """Refusals, citation defects and errors -- the behaviours that gate.

    Latency is deliberately absent: it lives in the reported block, because
    three runs that changed nothing moved a suite's p50 by 893 ms.
    """
    return [
        _no_change(
            "behaviour",
            f"{suite} refusals",
            sum(refused(record) for record in before_records),
            sum(refused(record) for record in after_records),
        ),
        _no_rise(
            "behaviour",
            f"{suite} invalid markers",
            before.answers_with_invalid_marker,
            after.answers_with_invalid_marker,
        ),
        _no_rise(
            "behaviour",
            f"{suite} answers with no citation",
            before.answers_with_no_citation,
            after.answers_with_no_citation,
        ),
        _no_rise("behaviour", f"{suite} errors", before.errors, after.errors),
    ]


def check_metrics(
    baseline_records: Sequence[EvalRecord],
    candidate_records: Sequence[EvalRecord],
) -> list[Check]:
    """Every gating metric, one block per question batch."""
    checks = []
    for suite in _suites(baseline_records):
        before_records = _subset(baseline_records, suite)
        after_records = _subset(candidate_records, suite)
        before, after = summarise(before_records), summarise(after_records)
        checks += _retrieval_checks(suite, before, after)
        checks += _behaviour_checks(suite, before, after, before_records, after_records)
        checks += _latency_checks(suite, before, after)
    return checks


def _reported(
    section: str,
    name: str,
    before: float | None,
    after: float | None,
    floor: float,
    digits: int = 0,
) -> Check:
    """A metric printed with its noise floor, never failing.

    The floor is shown so the reader sees "moved 4, floor is 4" rather than a
    number on its own -- and even a movement past the floor is reported rather
    than gated, because D-088's rule is that a generation change has to be read
    as a claim-level diff, not as a count that went from 11 to 7.
    """
    if before is None or after is None:
        moved = "n/a"
    else:
        moved = f"moved {abs(after - before):.{digits}f}, floor {floor:g}"
        if abs(after - before) > floor + EPSILON:
            moved += " -- CLEARS the floor, read the claim diff"
    return Check(
        section, name, _fmt(before, digits), _fmt(after, digits), moved, "report"
    )


def _latency_checks(suite: str, before: Summary, after: Summary) -> list[Check]:
    """p50 and time to first token, reported against their spreads.

    Both are reported rather than gated, and for opposite reasons. Total latency
    moved 893 ms across three runs that changed nothing, so it cannot fail a
    build. Time to first token is the number Phase 21 exists to move, and a gate
    whose rule is "must not get worse" would pass an improvement in silence --
    which is the one thing the gate was already known not to do.
    """
    return [
        _reported(
            "latency",
            f"{suite} p50 ms",
            before.p50_total_ms,
            after.p50_total_ms,
            LATENCY_NOISE_MS,
        ),
        _reported(
            "latency",
            f"{suite} p50 first token ms",
            before.p50_first_token_ms,
            after.p50_first_token_ms,
            TTFT_NOISE_MS,
        ),
    ]


def check_generation(baseline: Path, candidate: Path) -> list[Check]:
    """Faithfulness, reported. Returns nothing when either run was not judged."""
    if not all((run / "judgements.jsonl").exists() for run in (baseline, candidate)):
        return []
    before = judge_module.summarise(judge_module.read(baseline))
    after = judge_module.summarise(judge_module.read(candidate))
    return [
        _reported(
            "generation",
            "unsupported claims",
            before.unsupported,
            after.unsupported,
            UNSUPPORTED_FLOOR,
        ),
        _reported(
            "generation",
            "mean faithfulness",
            before.mean_faithfulness,
            after.mean_faithfulness,
            FAITHFULNESS_FLOOR,
            digits=4,
        ),
        _reported(
            "generation",
            "fully faithful answers",
            before.fully_faithful_answers,
            after.fully_faithful_answers,
            FULLY_FAITHFUL_FLOOR,
        ),
        _reported(
            "generation", "claims extracted", before.claims, after.claims, CLAIMS_FLOOR
        ),
    ]


def gate(
    baseline: Path, candidate: Path, changed: frozenset[str] = frozenset()
) -> Verdict:
    """Compare two saved runs and decide whether the candidate may pass.

    Comparability is checked first and nothing else runs if it fails. A table of
    metrics computed across two runs that were not measuring the same thing is
    worse than no table, because it looks exactly like one that was.
    """
    baseline_records = read_records(baseline)
    candidate_records = read_records(candidate)
    checks = check_comparability(
        read_meta(baseline),
        read_meta(candidate),
        baseline_records,
        candidate_records,
        changed,
    )
    if any(check.status == "fail" for check in checks):
        return Verdict(comparable=False, checks=checks)

    checks += check_metrics(baseline_records, candidate_records)
    checks += check_generation(baseline, candidate)
    return Verdict(comparable=True, checks=checks)


_MARK = {"pass": "ok  ", "fail": "FAIL", "warn": "warn", "report": "--  "}

# Gating sections first, reported ones last, so the part that can stop a build
# is not buried under the part that never can.
_SECTIONS = ("comparability", "retrieval", "behaviour", "latency", "generation")


def render(verdict: Verdict, baseline: str, candidate: str) -> str:
    """The gate's output: every check, grouped, with the reason on each line."""
    lines = [f"gate: {baseline} -> {candidate}", ""]
    for section in _SECTIONS:
        block = [check for check in verdict.checks if check.section == section]
        if not block:
            continue
        lines += ["", section.upper()]
        lines += [
            f"  {_MARK[check.status]} {check.name:<32} "
            f"{check.baseline:>10} -> {check.candidate:<10}  {check.rule}"
            for check in block
        ]

    lines.append("")
    if not verdict.comparable:
        lines.append(
            "INCOMPARABLE -- no metric was computed. Declare an intended "
            "difference with --changed <field>."
        )
    elif verdict.passed:
        lines.append(f"GATE PASSED -- {len(verdict.checks)} checks")
    else:
        lines.append(f"GATE FAILED -- {len(verdict.failures)} checks")
    return "\n".join(lines) + "\n"
