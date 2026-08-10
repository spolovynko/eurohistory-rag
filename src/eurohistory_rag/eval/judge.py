"""Is every claim in the answer actually in the sources it was shown?

The defect this exists for has been visible since Phase 6 and no metric in this
repository has ever counted it. The answer said the Treaty of Brest-Litovsk
"required Russia to pay war reparations of six billion marks"; the source says a
*supplementary protocol signed in August 1918* required it. Nothing was
invented, every citation resolved, recall was perfect -- and a reader would come
away with something untrue. Counting citations cannot see it. Only reading the
claim against its source can.

So that is what this does, mechanically: split the answer into standalone
claims, and ask a model, one claim at a time, whether the sources support it.

**Three known ways an LLM judge goes wrong, and what is done about each.**

*Position bias* -- preferring whichever candidate it saw first. Nothing here
compares two candidates, so there is no first. Removed by construction.

*Verbosity bias* -- preferring longer text. The score is supported claims over
total claims, so a longer answer must earn every extra claim it makes. A padded
answer scores worse, not better.

*Self-preference* -- preferring text from its own model family. Mitigated, not
removed: `judge_model` is its own setting so a different family can be swapped
in with one line, and the model that judged is recorded on every judgement. By
default it is the same family that answered, and that caveat travels with the
number.

The fourth control is not a prompt trick: `eval/probes.py` runs the judge
against hand-written claims whose verdict is already known, including the real
Brest-Litovsk defect above. A metric that cannot catch a defect we can point at
does not get trusted. Phase 7 shipped a metric that lied about refusals; this is
what was learned from it.
"""

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from eurohistory_rag.eval.metrics import refused
from eurohistory_rag.eval.record import EvalRecord
from eurohistory_rag.generation.client import (
    EmptyCompletion,
    GenerationUnavailable,
    Generator,
    complete,
)
from eurohistory_rag.generation.messages import Message

logger = logging.getLogger(__name__)

# A ceiling on cost, not on answers. The prompt asks for three to six sentences,
# so an answer producing more than this many claims has already broken a style
# rule and the extras are unlikely to change the score.
MAX_CLAIMS = 12

# Leading "1.", "- ", "* " and friends, which models add whatever the prompt
# says about format.
_BULLET = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")

# Citation markers, stripped before judging. "[2]" is a fact about our prompt,
# not part of the claim, and leaving it in invites the judge to grade the
# citation rather than the sentence.
_MARKER = re.compile(r"\[\d+\]")

CLAIM_INSTRUCTIONS = """\
You break an answer into the separate factual claims it makes.

Rules:
- One claim per line. No numbering, no bullets, no blank lines.
- Each claim must stand alone: replace "it", "the treaty", "there" with the \
name the answer used earlier.
- Keep every qualifier the answer gave -- dates, countries, "partly", \
"according to", who did what. A qualifier dropped here cannot be checked later.
- Copy the answer's wording. Do not correct it, soften it or improve it.

SPLITTING IS NOT FREE. Splitting comes last, after every rule above, and a \
qualifier is never split away from what it qualifies. Before you break a \
sentence in two, read each half on its own: if either half has lost a date, a \
figure's scope, an attribution, or the whole it is a part of, do not split it.

- A figure introduced by "including", "of whom", "of these", "among them" or \
"along with" is PART OF a larger figure. Carry the larger figure into the same \
line, or leave the sentence whole. "91,015 full-time, including 2,000 \
collaborators" must never become "employed 2,000 collaborators".
- A date, a place or a "but this includes..." clause belongs on the same line as \
the fact it limits.

IGNORE ANYTHING THAT IS NOT A CLAIM ABOUT THE WORLD. Hedges, refusals, and \
statements about what the sources do or do not cover. If the answer opens by \
saying the sources do not cover the question, reply with nothing at all, however \
many sentences follow -- an answer describing what the sources contain is making \
claims about the sources, not about history.

WORKED EXAMPLES

Answer: "The treaty was signed on 14 June 1985 by five member states."
Right: The treaty was signed on 14 June 1985 by five member states.
Wrong: two lines, because "signed by five member states" has lost the date and \
"signed on 14 June 1985" has lost who signed it.

Answer: "In 1989 it employed 91,015 people full-time, including 2,000 \
collaborators and 13,073 soldiers."
Right: In 1989 it employed 91,015 people full-time, including 2,000 \
collaborators and 13,073 soldiers.
Wrong: "In 1989 it employed 2,000 collaborators" -- that is a part reported as \
a whole.

Answer: "The sources do not cover what happened at Seveso. They mention it as \
an ecological disaster [1]."
Right: nothing at all.

Answer: "Poland's production grew 10% a year between 1971 and 1975, and living \
standards rose."
Right: two lines -- Poland's production grew 10% a year between 1971 and 1975. \
/ Poland's living standards rose between 1971 and 1975.

Reply with the claims and nothing else. If the answer makes no factual claim, \
reply with nothing.\
"""

VERDICT_INSTRUCTIONS = """\
You check one claim against a set of sources.

Finding the words of the claim in the sources is NOT enough. Before answering, \
run these two tests on the claim.

TEST 1 -- WHAT DOES IT ATTACH THE FACT TO?
Find the ONE sentence in the sources that carries the fact and read that \
sentence alone. Its own subject is what the fact attaches to -- not the title \
of the source, and not what surrounding sentences are about. If the claim \
attaches the same fact to anything else, answer NOT SUPPORTED.

You must quote that sentence's opening words back in your reply, so quote \
before you decide.

TEST 2 -- WHAT VERB DOES THE SOURCE USE?
"agreed to pay" is not "paid". "planned" is not "did". "demanded" is not \
"received". "was required to" is not "was". If the claim upgrades the source's \
verb to something stronger or more complete, answer NOT SUPPORTED.

Then:
- A rewording that keeps the meaning, the attachment and the verb IS \
SUPPORTED. You are checking meaning, not matching words. Do not fail a claim \
for using different words, rounding a figure it states, or being shorter.
- Your own knowledge is irrelevant. A claim that is true in the world but \
absent from the sources is NOT SUPPORTED.

WORKED EXAMPLES

Sources: <source id="1" title="The 1923 treaty">The 1923 treaty ended the \
war. A protocol signed in 1925 obliged the republic to pay two million \
francs.</source>
Claim: "The 1923 treaty obliged the republic to pay two million francs."
NOT SUPPORTED - "A protocol signed in 1925 obliged" - the protocol did, not \
the treaty

Sources: "The parties agreed to withdraw their forces by June."
Claim: "The parties withdrew their forces by June."
NOT SUPPORTED - "The parties agreed to withdraw" - agreeing is not doing

Sources: "Belgium received about 300 million dollars under the programme."
Claim: "The programme distributed about 300 million dollars."
NOT SUPPORTED - "Belgium received" - that figure is Belgium's share, not the \
programme's

Sources: "Industrial output fell by a third between 1929 and 1932."
Claim: "Production dropped by roughly 33% in the early 1930s."
SUPPORTED - "Industrial output fell by a third" - same figure and period, \
reworded

Reply with exactly one line and nothing else, quoting the sentence's opening \
words first:
SUPPORTED - "<opening words>" - <up to fifteen words>
NOT SUPPORTED - "<opening words>" - <up to fifteen words on what differs>\
"""


@dataclass(frozen=True, slots=True)
class Claim:
    """One factual claim from an answer, and the judge's verdict on it.

    `supported` is None when the judge replied with something that is neither
    verdict. Those are counted and excluded rather than folded into either
    side: a score that quietly treats "the judge did not answer" as "the system
    was wrong" is the same class of mistake as Phase 7's refusal metric.
    """

    text: str
    supported: bool | None
    reason: str


@dataclass(frozen=True, slots=True)
class Judgement:
    """Every claim in one answer, judged.

    `faithfulness` is None when there was nothing to judge -- a refusal, an
    error, or an answer that asserted nothing. Averaging a 0.0 in for those
    would report the system as unfaithful for correctly declining to answer.
    """

    question_id: str
    judge_model: str
    claims: list[Claim]
    faithfulness: float | None
    skipped: str = ""


def sources_block(record: EvalRecord) -> str:
    """The chunks the model was shown, numbered the way it saw them.

    Rebuilt from the record rather than re-retrieved: judging an answer against
    a fresh search would be judging it against sources it never had, which is a
    different and much easier test to pass.
    """
    shown = [item for item in record.retrieved[: record.sources_sent] if item.text]
    return "\n\n".join(
        f'<source id="{item.rank}" title="{item.source}">\n{item.text}\n</source>'
        for item in shown
    )


def parse_claims(text: str, limit: int = MAX_CLAIMS) -> list[str]:
    """The model's claim list as clean lines."""
    claims = []
    for line in text.splitlines():
        stripped = _MARKER.sub("", _BULLET.sub("", line)).strip()
        if len(stripped) > 10:
            claims.append(stripped)
    return claims[:limit]


def parse_verdict(text: str) -> tuple[bool | None, str]:
    """Read one verdict line as (supported, reason).

    "NOT SUPPORTED" is tested first because it contains "SUPPORTED": checking
    the other way round marks every failure as a pass, silently, and the
    resulting metric would report a perfect score forever.
    """
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    upper = line.upper()
    reason = line.split("-", 1)[1].strip() if "-" in line else line

    if upper.startswith("NOT SUPPORTED"):
        return False, reason
    if upper.startswith("SUPPORTED"):
        return True, reason
    logger.warning("unparseable verdict: %r", line)
    return None, line


def extract_claims(answer: str, generator: Generator) -> list[str]:
    """Split an answer into the claims it makes, or none if it makes none.

    An empty reply is the instructed answer here, not a failure: a refusal
    asserts nothing about the world and must yield no claims. Every other way
    the model can fail still raises. D-102.
    """
    messages: list[Message] = [
        {"role": "system", "content": CLAIM_INSTRUCTIONS},
        {"role": "user", "content": answer},
    ]
    try:
        return parse_claims(complete(generator, messages).text)
    except EmptyCompletion:
        return []


def judge_claim(claim: str, sources: str, generator: Generator) -> Claim:
    """Ask whether the sources support one claim.

    One call per claim rather than one call per answer. It costs more and it is
    what makes the bias argument hold: a claim judged on its own cannot be
    carried by a confident neighbour, and the length of the answer it came from
    is invisible to the judge.
    """
    messages: list[Message] = [
        {"role": "system", "content": VERDICT_INSTRUCTIONS},
        {"role": "user", "content": f"{sources}\n\n# CLAIM\n\n{claim}"},
    ]
    supported, reason = parse_verdict(complete(generator, messages).text)
    return Claim(text=claim, supported=supported, reason=reason)


def score(claims: Sequence[Claim]) -> float | None:
    """Supported claims over judged claims, or None if none could be judged."""
    judged = [claim for claim in claims if claim.supported is not None]
    if not judged:
        return None
    return sum(claim.supported is True for claim in judged) / len(judged)


def judge_record(record: EvalRecord, generator: Generator) -> Judgement:
    """Judge one answer, claim by claim.

    Refusals and errors are skipped with a reason rather than scored. "Not in
    the sources." is the system working, and it makes no claim to check.
    """
    empty = Judgement(record.question_id, generator.model, [], None)
    if record.error:
        return replace(empty, skipped="generation error")
    if refused(record):
        return replace(empty, skipped="refusal")

    sources = sources_block(record)
    if not sources:
        return replace(empty, skipped="no source text recorded")

    try:
        claims = extract_claims(record.answer, generator)
        judged = [judge_claim(claim, sources, generator) for claim in claims]
    except GenerationUnavailable as error:
        logger.warning("%s: judge failed: %s", record.question_id, error)
        return replace(empty, skipped=f"judge failed: {error}")

    if not judged:
        return replace(empty, skipped="no factual claims")

    return Judgement(
        question_id=record.question_id,
        judge_model=generator.model,
        claims=judged,
        faithfulness=score(judged),
    )


def judge_all(records: Sequence[EvalRecord], generator: Generator) -> list[Judgement]:
    """Judge every answer in a run, in order."""
    judgements = []
    for position, record in enumerate(records, start=1):
        logger.info("[%d/%d] %s", position, len(records), record.question_id)
        judgements.append(judge_record(record, generator))
    return judgements


@dataclass(frozen=True, slots=True)
class FaithfulnessSummary:
    """A run's faithfulness, reduced to the numbers worth comparing."""

    answers_judged: int
    answers_skipped: int
    claims: int
    supported: int
    unsupported: int
    unparseable: int
    mean_faithfulness: float | None
    fully_faithful_answers: int


def summarise(judgements: Sequence[Judgement]) -> FaithfulnessSummary:
    """Reduce a set of judgements to one row.

    `mean_faithfulness` averages per answer rather than over all claims, so a
    single long answer cannot dominate. `fully_faithful_answers` is the number
    that matters in practice: a 90% mean sounds fine and means one claim in ten
    is not in the sources.
    """
    scored = [j for j in judgements if j.faithfulness is not None]
    claims = [claim for j in judgements for claim in j.claims]
    means = [j.faithfulness for j in scored if j.faithfulness is not None]

    return FaithfulnessSummary(
        answers_judged=len(scored),
        answers_skipped=len(judgements) - len(scored),
        claims=len(claims),
        supported=sum(claim.supported is True for claim in claims),
        unsupported=sum(claim.supported is False for claim in claims),
        unparseable=sum(claim.supported is None for claim in claims),
        mean_faithfulness=sum(means) / len(means) if means else None,
        fully_faithful_answers=sum(j.faithfulness == 1.0 for j in scored),
    )


def render(judgements: Sequence[Judgement], summary: FaithfulnessSummary) -> str:
    """The unsupported claims, in full, with the summary on top.

    Prints what failed rather than only how much: a faithfulness number nobody
    can act on is a number nobody will act on, and the judge itself is on trial
    every time this file is read.
    """
    mean = (
        "n/a"
        if summary.mean_faithfulness is None
        else f"{summary.mean_faithfulness:.1%}"
    )
    lines = [
        f"judge: {judgements[0].judge_model if judgements else 'none'}",
        "",
        f"answers judged   {summary.answers_judged}",
        f"answers skipped  {summary.answers_skipped}  (refusals, errors, no claims)",
        f"claims           {summary.claims}",
        f"  supported      {summary.supported}",
        f"  unsupported    {summary.unsupported}",
        f"  unparseable    {summary.unparseable}",
        f"mean faithfulness  {mean}",
        f"fully faithful     {summary.fully_faithful_answers}/{summary.answers_judged}",
        "",
        "=" * 78,
        "UNSUPPORTED CLAIMS -- read these, they are the point of the metric",
        "=" * 78,
    ]
    for judgement in judgements:
        failures = [c for c in judgement.claims if c.supported is not True]
        if not failures:
            continue
        lines.append("")
        lines.append(f"[{judgement.question_id}]")
        for claim in failures:
            verdict = "UNSUPPORTED" if claim.supported is False else "UNJUDGED"
            lines += [f"  {verdict}: {claim.text}", f"    -> {claim.reason}"]
    return "\n".join(lines) + "\n"


def write(directory: Path, judgements: Sequence[Judgement]) -> Path:
    """Write judgements beside the run they judge, without touching it.

    A separate file rather than a field on the record: records are immutable
    (D-068), judging happens later and costs money, and a re-judge with a
    better prompt must never be able to damage the run it read.
    """
    path = directory / "judgements.jsonl"
    lines = (json.dumps(asdict(j), ensure_ascii=False) for j in judgements)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read(directory: Path) -> list[Judgement]:
    """Load judgements back, for comparing two runs without paying again."""
    path = directory / "judgements.jsonl"
    judgements = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        raw["claims"] = [Claim(**claim) for claim in raw["claims"]]
        judgements.append(Judgement(**raw))
    return judgements
