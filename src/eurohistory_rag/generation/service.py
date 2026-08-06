"""Question in, grounded answer out.

The recipe /ask follows: find the chunks, build the messages, ask the model,
and hand back the answer with only the sources it actually cited. It sits
above SearchService rather than inside it, because retrieval is useful on its
own -- /search proves that -- and generation is not useful without retrieval.
"""

import logging
import re
from dataclasses import dataclass

from eurohistory_rag.generation.client import Generator
from eurohistory_rag.generation.messages import build_messages
from eurohistory_rag.generation.verify import verify
from eurohistory_rag.retrieval.search import SearchResult, SearchService

logger = logging.getLogger(__name__)

# The marker the prompt tells the model to write: [1], [3] and so on.
CITATION = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True, slots=True)
class Citation:
    """One source the answer actually used.

    `number` is what appears in the text; everything else is what a reader
    needs to go and check the claim.
    """

    number: int
    result: SearchResult


@dataclass(frozen=True, slots=True)
class Answer:
    """A grounded answer and the sources behind it."""

    question: str
    text: str
    model: str
    citations: list[Citation]
    # What the call cost. Carried on the answer rather than logged and dropped,
    # because Phase 7 reports cost per question and the API layer is free to
    # ignore fields it does not expose.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Whether the groundedness gate changed anything. False also means "the
    # gate was off", and the two are told apart by meta.json rather than here:
    # the eval needs a firing rate, and an answer does not need to know why it
    # was left alone. Phase 13, D-084.
    revised: bool = False
    # The pre-gate text, kept only when the gate changed something. Reading a
    # revision means putting it next to what it replaced, and at a firing rate
    # of a few percent no aggregate metric can see the gate at all -- so the
    # pair is the measurement. Empty when nothing was revised.
    draft: str = ""


def _total(first: int | None, second: int | None) -> int | None:
    """One question's token cost across both calls, or None if either is unknown.

    An absent count stays absent rather than becoming a zero, for the same
    reason Completion keeps them optional: a wrong number averages into the
    cost-per-question figure and a missing one does not.
    """
    return None if first is None else first + (second or 0)


def cited(text: str, results: list[SearchResult]) -> list[Citation]:
    """The sources the answer refers to, in the order it refers to them.

    A number the model invented -- [7] when six sources were given -- is
    dropped rather than raising: the answer is still worth returning, and
    Phase 7 counts these as a measure of whether the prompt holds.
    """
    seen: set[int] = set()
    citations: list[Citation] = []
    for match in CITATION.finditer(text):
        number = int(match.group(1))
        if number in seen or not 1 <= number <= len(results):
            continue
        seen.add(number)
        citations.append(Citation(number=number, result=results[number - 1]))
    return citations


class GenerationService:
    """Answers a question from the corpus, with citations."""

    def __init__(
        self,
        search: SearchService,
        generator: Generator,
        verifier: Generator | None = None,
    ) -> None:
        self._search = search
        self._generator = generator
        # The groundedness gate, or None when it is off. Presence rather than a
        # boolean plus a client: one concept to reason about, one thing that can
        # be forgotten. It is a `Generator` because checking is the same shape
        # as answering -- messages in, text out -- with a different prompt.
        self._verifier = verifier

    def ask(self, question: str, k: int | None = None) -> Answer:
        """Find the chunks, ask the model, return the answer and its sources.

        No shortcut when retrieval comes back empty: the prompt already has a
        rule for that case, and letting one code path handle every refusal
        means there is only one behaviour to test and to fix.
        """
        return self.answer_from(question, self._search.search(question, k=k))

    def answer_from(self, question: str, results: list[SearchResult]) -> Answer:
        """Answer from chunks already retrieved.

        The half of `ask` that does not search. Split out for the evaluation
        runner, which needs one search of its own to score retrieval and must
        then generate from exactly the shipped path rather than a copy of it --
        a copy would drift, and the eval would stop measuring the real system.
        """
        completion = self._generator.generate(build_messages(question, results))
        text = completion.text
        prompt_tokens = completion.prompt_tokens
        completion_tokens = completion.completion_tokens
        revised = False

        if self._verifier is not None:
            checked = verify(self._verifier, question, results, completion.text)
            text = checked.text
            revised = checked.changed
            prompt_tokens = _total(prompt_tokens, checked.prompt_tokens)
            completion_tokens = _total(completion_tokens, checked.completion_tokens)

        # Read back out of the *shipped* text, not the draft: the gate may have
        # deleted a sentence, and a citation list naming a source no longer
        # referred to is the kind of quiet inconsistency nobody notices until a
        # reader clicks the link.
        citations = cited(text, results)
        logger.info(
            "ask %r: %d sources, %d cited, revised=%s",
            question,
            len(results),
            len(citations),
            revised,
        )
        return Answer(
            question=question,
            text=text,
            model=self._generator.model,
            citations=citations,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            revised=revised,
            draft=completion.text if revised else "",
        )
