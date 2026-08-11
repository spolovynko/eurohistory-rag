"""Question in, grounded answer out.

The recipe /ask follows: find the chunks, build the messages, ask the model,
and hand back the answer with only the sources it actually cited. It sits
above SearchService rather than inside it, because retrieval is useful on its
own -- /search proves that -- and generation is not useful without retrieval.
"""

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace

from eurohistory_rag.core.trace import Trace
from eurohistory_rag.generation.cache import SemanticCache
from eurohistory_rag.generation.client import (
    Completion,
    GenerationUnavailable,
    Generator,
    complete,
)
from eurohistory_rag.generation.messages import build_messages
from eurohistory_rag.generation.rewrite import Turn, rewrite
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
    # The share of `prompt_tokens` the provider served from cache and charged a
    # quarter for. Summed across the writing call and the checking call, so it
    # is comparable with `prompt_tokens` beside it. D-103.
    cached_tokens: int | None = None
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
    # Milliseconds from the model being asked to the first word coming back.
    # Generation only -- the caller knows what its own search cost and adds it,
    # because this object has no idea whether one happened. None when nothing
    # streamed, which is what the groundedness gate forces. D-095.
    first_token_ms: float | None = None
    # The question this text was originally written for, when it was served from
    # the semantic cache; empty when the model wrote it just now. This is the
    # disclosure: an answer produced for a different wording is not the same
    # object as an answer produced for yours, and a system whose selling point
    # is grounding does not get to blur that. Phase 31.
    cached_from: str = ""


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
        rewriter: Generator | None = None,
        cache: "SemanticCache[Answer] | None" = None,
    ) -> None:
        self._search = search
        # Answers already written, findable by what a question meant. None when
        # the cache is off, which is the default and is what the eval runs on:
        # three of its conversation controls are byte-identical to golden
        # questions, and a cache would serve them the earlier answer and destroy
        # the thing they were written to measure. Phase 31.
        self._cache = cache
        self._generator = generator
        # The model that turns a follow-up into a standalone question, or None
        # when conversation is off. Its own client rather than a flag on the
        # answering one, for the reason the verifier is: they are two different
        # jobs and there is no rule saying the same model has to be good at
        # both. D-098.
        self._rewriter = rewriter
        # The groundedness gate, or None when it is off. Presence rather than a
        # boolean plus a client: one concept to reason about, one thing that can
        # be forgotten. It is a `Generator` because checking is the same shape
        # as answering -- messages in, text out -- with a different prompt.
        self._verifier = verifier

    def standalone(
        self,
        question: str,
        history: Sequence[Turn] = (),
        trace: Trace | None = None,
    ) -> str:
        """The question with the conversation folded into it.

        A second turn is not a question -- "when did it come down?" has no
        subject, and the subject is in the turn above. This is where that gets
        put back, and it is deliberately the *only* place: everything downstream
        keeps receiving one self-contained question, so retrieval, the prompt,
        the citations and every metric are unchanged.

        Returns the question untouched when there is no history or no rewriter,
        which is every one of the 92 single-turn evaluation questions and every
        first turn anyone ever types. D-098.
        """
        if self._rewriter is None or not history:
            return question
        if trace is None:
            trace = Trace()
        with trace.span("rewrite") as span:
            rewritten = rewrite(self._rewriter, question, history)
            span.note = f"{len(history)} turns of history"
        return rewritten

    def ask(
        self, question: str, k: int | None = None, trace: Trace | None = None
    ) -> Answer:
        """Find the chunks, ask the model, return the answer and its sources.

        No shortcut when retrieval comes back empty: the prompt already has a
        rule for that case, and letting one code path handle every refusal
        means there is only one behaviour to test and to fix.
        """
        if trace is None:
            trace = Trace()
        results, vector = self.search_with_vector(question, k=k, trace=trace)
        return self.answer_from(question, results, vector=vector, trace=trace)

    def search_with_vector(
        self, question: str, k: int | None = None, trace: Trace | None = None
    ) -> tuple[list[SearchResult], list[float]]:
        """Retrieval, plus the vector the question became.

        The vector is what the answer cache is keyed on. Handed up from the
        search rather than made here, because the search already paid for it --
        the cache costs nothing extra to consult, which is the only reason it
        can sit in front of every question rather than only the repeated ones.
        """
        return self._search.search_with_vector(question, k=k, trace=trace)

    def search(
        self, question: str, k: int | None = None, trace: Trace | None = None
    ) -> list[SearchResult]:
        """The retrieval half, on its own.

        Public because /ask has to do it *before* a streaming response begins:
        once the first byte is out the status code has been sent and a dead
        Qdrant can no longer be a 503. Doing the half that can fail early is
        what keeps that failure honest.
        """
        return self._search.search(question, k=k, trace=trace)

    def answer_from(
        self,
        question: str,
        results: list[SearchResult],
        trace: Trace | None = None,
        *,
        vector: Sequence[float] | None = None,
    ) -> Answer:
        """Answer from chunks already retrieved.

        The half of `ask` that does not search. Split out for the evaluation
        runner, which needs one search of its own to score retrieval and must
        then generate from exactly the shipped path rather than a copy of it --
        a copy would drift, and the eval would stop measuring the real system.

        `vector` is the question's embedding, and passing none simply turns the
        cache off for this call -- which is what the eval runner and every test
        that builds results by hand do today.
        """
        for piece in self.stream_from(question, results, vector=vector, trace=trace):
            if isinstance(piece, Answer):
                return piece
        raise GenerationUnavailable("The answer stream ended without an answer.")

    def stream_from(
        self,
        question: str,
        results: list[SearchResult],
        trace: Trace | None = None,
        *,
        vector: Sequence[float] | None = None,
    ) -> Iterator[str | Answer]:
        """The answer as the model writes it, then the finished Answer.

        Same shape as `Generator.stream` one layer down: strings are more of the
        answer, and the single `Answer` at the end is the thing with citations
        resolved. Citations cannot come earlier -- a marker is only a citation
        once the text holding it exists.

        **Nothing streams while the groundedness gate is on.** The gate reads
        the finished draft and may delete a sentence from it, and text shown and
        then taken back is worse than text that arrived late. So with a verifier
        configured this yields the answer in one piece and reports no first
        token, which the eval reads as "arrived at the end".

        **What the `generate` span measures when streaming**: wall clock from
        asking the model to the last piece arriving here, which includes
        whatever the consumer did between pieces. For the eval runner that is a
        tight loop and the difference is microseconds; for the page it is one
        `json.dumps` per token. Named rather than engineered around -- the
        honest quantity is "how long the reader waited", not "how long the
        model was busy". D-101.
        """
        if trace is None:
            trace = Trace()

        served = self._from_cache(question, vector, trace)
        if served is not None:
            # The whole answer in one piece. A cached answer has no first token
            # to wait for, so there is nothing to stream and pretending
            # otherwise would only make the page look busy.
            yield served.text
            yield served
            return

        with trace.span("prompt") as span:
            messages = build_messages(question, results)
            span.note = f"{len(results)} sources"

        if self._verifier is not None:
            with trace.span("generate") as span:
                gated = complete(self._generator, messages)
                span.note = "not streamed: the gate is on"
            yield self._keep(
                question, vector, self._finish(question, results, gated, trace)
            )
            return

        completion: Completion | None = None
        with trace.span("generate") as span:
            for piece in self._generator.stream(messages):
                if isinstance(piece, Completion):
                    completion = piece
                else:
                    yield piece
            span.note = (
                "no completion"
                if completion is None or completion.first_token_ms is None
                else f"first token at {completion.first_token_ms:.0f} ms"
            )
        if completion is None:
            raise GenerationUnavailable("The model's stream ended without an answer.")
        yield self._keep(
            question, vector, self._finish(question, results, completion, trace)
        )

    def _from_cache(
        self, question: str, vector: Sequence[float] | None, trace: Trace
    ) -> Answer | None:
        """A previously written answer close enough in meaning to serve, if any.

        What comes back is deliberately *not* the stored object. Three fields
        are rewritten and each is a small honesty:

        - `question` becomes the one that was asked and `cached_from` the one
          the text was written for, so the disclosure travels with the answer
          rather than being the caller's job to remember.
        - The token counts go to zero. They are what this question cost, and
          this question cost nothing; leaving the original's counts in place
          would bill a run twice for words bought once.
        - `revised` and `draft` are cleared. The groundedness gate did not run
          on this request, and a firing rate that counted cache hits would be
          measuring history rather than the gate.

        The citations are the *stored* ones, not the ones just retrieved. The
        [1] markers in the text point at the sources the writer was shown, and
        renumbering them onto a fresh search would silently attach the answer's
        claims to chunks nobody wrote it from -- which is the exact failure this
        phase is built to avoid, arriving through the back door.
        """
        if self._cache is None or vector is None:
            return None
        with trace.span("cache") as span:
            hit = self._cache.lookup(vector)
            span.note = "miss" if hit is None else f"hit at {hit.similarity:.4f}"
        if hit is None:
            return None
        logger.info(
            "cache hit %r served by %r at %.4f", question, hit.question, hit.similarity
        )
        return replace(
            hit.value,
            question=question,
            cached_from=hit.question,
            prompt_tokens=0,
            completion_tokens=0,
            cached_tokens=0,
            revised=False,
            draft="",
            first_token_ms=0.0,
        )

    def _keep(
        self, question: str, vector: Sequence[float] | None, answer: Answer
    ) -> Answer:
        """Put a freshly written answer on the shelf, and hand it back unchanged.

        Returns the answer so it can wrap the `yield` at the end of both
        branches: storing is a side effect of finishing, and separating them
        would leave one branch that could be edited without the other.
        """
        if self._cache is not None and vector is not None:
            self._cache.store(question, vector, answer)
        return answer

    def _finish(
        self,
        question: str,
        results: list[SearchResult],
        completion: Completion,
        trace: Trace,
    ) -> Answer:
        """Run the groundedness gate if there is one, then resolve the markers."""
        text = completion.text
        prompt_tokens = completion.prompt_tokens
        completion_tokens = completion.completion_tokens
        cached_tokens = completion.cached_tokens
        revised = False

        if self._verifier is not None:
            with trace.span("verify") as span:
                checked = verify(self._verifier, question, results, completion.text)
                span.note = "revised" if checked.changed else "left alone"
            text = checked.text
            revised = checked.changed
            prompt_tokens = _total(prompt_tokens, checked.prompt_tokens)
            completion_tokens = _total(completion_tokens, checked.completion_tokens)
            cached_tokens = _total(cached_tokens, checked.cached_tokens)

        # Read back out of the *shipped* text, not the draft: the gate may have
        # deleted a sentence, and a citation list naming a source no longer
        # referred to is the kind of quiet inconsistency nobody notices until a
        # reader clicks the link.
        with trace.span("cite") as span:
            citations = cited(text, results)
            span.note = f"{len(citations)} of {len(results)} used"
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
            cached_tokens=cached_tokens,
            revised=revised,
            draft=completion.text if revised else "",
            # A gated answer was not streamed, whatever the draft's own clock
            # says: the reader waited for the check as well.
            first_token_ms=None if self._verifier else completion.first_token_ms,
        )
