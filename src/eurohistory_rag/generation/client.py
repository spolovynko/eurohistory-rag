"""Turning a message list into an answer.

The only place a generation model is chosen, and the only module that touches
the OpenAI chat API. Everything above it works in plain strings, so faking the
model in tests or swapping the provider changes nothing else.
"""

import logging
from collections.abc import Sequence
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


class Generator(Protocol):
    """Messages in, answer out."""

    @property
    def model(self) -> str:
        """The model that answers, for the record kept on each answer."""
        ...

    def generate(self, messages: Sequence[Message]) -> Completion:
        """Return the model's answer to this conversation, and its token cost."""
        ...


class OpenAIGenerator:
    """Generator backed by the OpenAI chat completions API."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key, max_retries=MAX_RETRIES)
        self._model = model

    @property
    def model(self) -> str:
        """The model that answers, for the record kept on each answer."""
        return self._model

    def generate(self, messages: Sequence[Message]) -> Completion:
        """Ask the model and return its answer.

        Every failure becomes GenerationUnavailable, so no caller ever has to
        know an OpenAI exception exists -- the API layer turns it into a 503
        and the rest of the system stays provider-agnostic.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=cast(list[ChatCompletionMessageParam], list(messages)),
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except OpenAIError as error:
            logger.warning("generation failed: %s", error)
            raise GenerationUnavailable(str(error)) from error

        answer = response.choices[0].message.content
        if not answer:
            raise GenerationUnavailable("The model returned an empty answer.")

        usage = response.usage
        return Completion(
            text=answer.strip(),
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
