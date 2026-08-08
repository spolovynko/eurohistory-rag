"""Turning a message list into an answer.

The only place a generation model is chosen, and the only module that touches
the OpenAI chat API. Everything above it works in plain strings, so faking the
model in tests or swapping the provider changes nothing else.
"""

import logging
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from eurohistory_rag.generation.messages import Message

logger = logging.getLogger(__name__)

# Same question and same sources give the same answer. Phase 7 compares thirty
# answers before and after a change, and a model that wanders makes that
# comparison meaningless.
TEMPERATURE = 0.0

# A ceiling, not a target. The prompt asks for three to six sentences, so an
# answer anywhere near this limit means the style rules were ignored.
MAX_OUTPUT_TOKENS = 800

# The SDK retries 429s and 5xx itself, same as the embedder does.
MAX_RETRIES = 5


class GenerationUnavailable(RuntimeError):
    """The model could not be reached, or returned nothing usable."""


@dataclass(frozen=True, slots=True)
class Completion:
    """What the model sent back: the answer, and what it cost.

    The token counts are the only measure of cost this system has, and Phase 7
    needs them per question. They are optional because a provider is not
    obliged to report them and a fake never can -- an absent count is honest,
    where a zero would quietly average into the wrong number.
    """

    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Milliseconds from the request leaving to the first word of the answer
    # arriving. The number a reader experiences as "slow"; total time is not,
    # because an answer that starts in one second and finishes in five feels
    # quicker than one that appears whole at four. None when nothing streamed.
    first_token_ms: float | None = None


class Generator(Protocol):
    """Messages in, answer out -- in pieces, as the model writes it.

    One method rather than two. A `generate` alongside `stream` would be a
    second way to call a model, and Phase 8 is the standing reminder of what a
    second path costs: the eval and the page would each pick one and nobody
    would notice they had stopped measuring the same thing. Callers that want
    the whole answer use `complete()` below, which is the loop written once.
    """

    @property
    def model(self) -> str:
        """The model that answers, for the record kept on each answer."""
        ...

    def stream(self, messages: Sequence[Message]) -> Iterator[str | Completion]:
        """Yield the answer in pieces, then one Completion holding the whole.

        The union is the contract and it is deliberately plain: a `str` is more
        of the answer, and the single `Completion` at the end is the finished
        thing with its token cost. Token usage only arrives once the model has
        stopped, so it cannot be reported any earlier than this.
        """
        ...


def complete(generator: Generator, messages: Sequence[Message]) -> Completion:
    """The whole answer, for a caller with nothing to do with the pieces.

    The eval runner and the JSON half of /ask both want one object. This is
    that, written once, over the same call the page streams -- so a change to
    how the model is asked cannot reach one of them and miss the other.
    """
    for piece in generator.stream(messages):
        if isinstance(piece, Completion):
            return piece
    raise GenerationUnavailable("The model's stream ended without an answer.")


class OpenAIGenerator:
    """Generator backed by the OpenAI chat completions API."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key, max_retries=MAX_RETRIES)
        self._model = model

    @property
    def model(self) -> str:
        """The model that answers, for the record kept on each answer."""
        return self._model

    def stream(self, messages: Sequence[Message]) -> Iterator[str | Completion]:
        """Ask the model and hand back its answer as it is written.

        Every failure becomes GenerationUnavailable, so no caller ever has to
        know an OpenAI exception exists -- the API layer turns it into a 503
        and the rest of the system stays provider-agnostic. A failure part-way
        through a stream raises here too, and reaches the caller mid-iteration:
        by then some of the answer has already been handed over, which is the
        one thing streaming makes harder and /ask has to render honestly.

        `include_usage` is not optional. Without it a streamed call reports no
        token counts at all, `eval/cost.py` loses the only price this project
        measures, and it fails silently -- the run still writes, with a blank
        where the money was.
        """
        started = time.perf_counter()
        first_token_ms: float | None = None
        pieces: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None

        try:
            chunks = self._client.chat.completions.create(
                model=self._model,
                messages=cast(list[ChatCompletionMessageParam], list(messages)),
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in chunks:
                if chunk.usage is not None:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content or ""
                if first_token_ms is None:
                    # Leading blank lines are not an answer arriving, and a
                    # clock started on one would flatter the number this whole
                    # phase is measured by.
                    delta = delta.lstrip()
                    if not delta:
                        continue
                    first_token_ms = round((time.perf_counter() - started) * 1000, 1)
                elif not delta:
                    continue
                pieces.append(delta)
                yield delta
        except OpenAIError as error:
            logger.warning("generation failed: %s", error)
            raise GenerationUnavailable(str(error)) from error

        text = "".join(pieces).rstrip()
        if not text:
            raise GenerationUnavailable("The model returned an empty answer.")

        yield Completion(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            first_token_ms=first_token_ms,
        )
