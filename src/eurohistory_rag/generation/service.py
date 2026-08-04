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

    def __init__(self, search: SearchService, generator: Generator) -> None:
        self._search = search
        self._generator = generator

    def ask(self, question: str, k: int | None = None) -> Answer:
        """Find the chunks, ask the model, return the answer and its sources.

        No shortcut when retrieval comes back empty: the prompt already has a
        rule for that case, and letting one code path handle every refusal
        means there is only one behaviour to test and to fix.
        """
        results = self._search.search(question, k=k)
        messages = build_messages(question, results)
        text = self._generator.generate(messages)
        citations = cited(text, results)
        logger.info(
            "ask %r: %d sources, %d cited", question, len(results), len(citations)
        )
        return Answer(
            question=question,
            text=text,
            model=self._generator.model,
            citations=citations,
        )
