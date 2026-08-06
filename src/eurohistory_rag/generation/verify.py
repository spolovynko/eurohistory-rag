"""The second reader: a draft answer checked against its sources before it ships.

Every fix for an ungrounded claim in this project so far has been an instruction
inside the writing step -- Phase 6's grounding rule, Phase 11's rule about the
joins between facts. Both helped and neither closed it. The Trianon reversal
survived Phase 11's rule *and* Phase 12's retrieval change, and the reason is
visible in the transcript: the question asks what Hungary lost, so every sentence
is written with Hungary as the subject, and the question's subject beats the
source sentence's. A rule inside the writing step cannot see an error the
writing step is making. A second pass can, because it reads the finished
sentence instead of intending it.

No new Protocol here. `Generator` is already "messages in, answer out", and the
gate is that same shape with a different prompt -- so the fake used in the tests
and the swap to another provider both come for free.

**Three things this module refuses to trust the prompt about**, because a prompt
instruction is not a guarantee and this repository has three sightings of it:
the gate may not turn an answer into a refusal, may not return nothing, and may
not take the answer away when the model is unreachable. Each is enforced in code
below rather than only in verify_prompt.md.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files

from eurohistory_rag.generation.client import (
    Completion,
    GenerationUnavailable,
    Generator,
)
from eurohistory_rag.generation.messages import Message, format_sources
from eurohistory_rag.retrieval.search import SearchResult

logger = logging.getLogger(__name__)

VERIFY_PROMPT = (
    files("eurohistory_rag.generation")
    .joinpath("verify_prompt.md")
    .read_text(encoding="utf-8")
)

# The exact phrase system_prompt.md reserves for a refusal. Phase 7 shipped a
# metric that guessed this string instead of reading it and reported 0% refusals
# for a system that was refusing correctly -- so it is read from one place only.
REFUSAL = "Not in the sources."

# The checker works claim by claim before it edits, and writes that working out
# in a <check> block. The first version of this prompt asked for the answer
# alone and caught none of the three defects it was probed against: reading a
# fluent answer whole produces the impression that it is fine, which is exactly
# how a reversed subject survives. So the reasoning is required, and this is
# what separates it from the answer afterwards.
ANSWER_BLOCK = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Verified:
    """The answer that should ship, and what the check cost.

    `changed` is what the eval counts: a gate that never fires is dead code, and
    one that fires on every answer is rewriting drafts that were already right.
    The token counts are kept even when the revision is discarded, because the
    call was paid for either way.
    """

    text: str
    changed: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def build_verify_messages(
    question: str, results: Sequence[SearchResult], draft: str
) -> list[Message]:
    """The two messages the checking call receives.

    The same sources in the same order the writer saw, so the check is against
    what was actually in front of it -- a checker shown different evidence is
    grading a different answer. The draft goes last, where a model reads
    hardest.
    """
    user = (
        f"{format_sources(results)}\n\n"
        f"# QUESTION\n\n{question}\n\n"
        f"# DRAFT ANSWER\n\n{draft}"
    )
    return [
        {"role": "system", "content": VERIFY_PROMPT},
        {"role": "user", "content": user},
    ]


def _unchanged(revised: str, draft: str) -> bool:
    """Whitespace-insensitive comparison, because reflowing is not a correction.

    A model that returns the same sentences wrapped differently has changed
    nothing worth counting, and counting it would inflate the one number that
    says whether this gate does anything.
    """
    return revised.split() == draft.split()


def verify(
    generator: Generator,
    question: str,
    results: Sequence[SearchResult],
    draft: str,
) -> Verified:
    """Return the answer that should ship: the draft, or a corrected version.

    Every failure path keeps the draft. An answer already exists and is already
    grounded 99% of the time; losing it because the checker was unreachable, or
    replacing it with a refusal the checker invented, would make this change a
    net loss on exactly the runs where it is meant to help.
    """
    if not draft.strip() or draft.startswith(REFUSAL):
        return Verified(text=draft, changed=False)

    try:
        completion = generator.generate(build_verify_messages(question, results, draft))
    except GenerationUnavailable as error:
        logger.warning("verification unavailable, keeping the draft: %s", error)
        return Verified(text=draft, changed=False)

    return _decide(completion, draft)


def _decide(completion: Completion, draft: str) -> Verified:
    """Accept the revision, or keep the draft and say why in the log."""
    kept = Verified(
        text=draft,
        changed=False,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )

    block = ANSWER_BLOCK.search(completion.text)
    if block is None:
        # Both tags or nothing. Without them there is no way to tell the
        # checker's working out from the answer, and shipping its reasoning to
        # a reader is worse than shipping the unchecked draft. A reply cut off
        # by the token ceiling lands here too, which is the safe place for it.
        logger.warning("verification returned no <answer> block, keeping the draft")
        return kept

    revised = block.group(1).strip()
    if not revised:
        logger.warning("verification returned nothing, keeping the draft")
        return kept
    if revised.startswith(REFUSAL):
        logger.warning("verification tried to refuse, keeping the draft")
        return kept

    changed = not _unchanged(revised, draft)
    if changed:
        logger.info("verification revised the answer")
    return Verified(
        text=revised,
        changed=changed,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )
