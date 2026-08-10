"""Tests for the streaming model client.

Nothing here reaches OpenAI. The SDK object is replaced with a stand-in that
yields the chunk shapes the real one yields, because what is being checked is
our handling of them -- where the clock starts, where the token counts come
from, and what an empty stream becomes.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from openai import APIConnectionError

from eurohistory_rag.generation.client import (
    Completion,
    EmptyCompletion,
    GenerationUnavailable,
    OpenAIGenerator,
    complete,
)
from tests.fakes import FakeGenerator

# --- a stand-in for the SDK --------------------------------------------------


@dataclass
class Delta:
    content: str | None


@dataclass
class Choice:
    delta: Delta


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class Chunk:
    """One streamed chunk, in the shape the OpenAI SDK produces.

    A chunk carries text or usage, never both: the counts arrive in a final
    chunk with an empty `choices` list, which is exactly the case a reader of
    our loop has to get right.
    """

    choices: list[Choice]
    usage: Usage | None = None


def text_chunk(content: str | None) -> Chunk:
    return Chunk(choices=[Choice(delta=Delta(content=content))])


class StubCompletions:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> Iterator[Chunk]:
        self.kwargs = kwargs
        return iter(self._chunks)


class StubClient:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chat = type("Chat", (), {"completions": StubCompletions(chunks)})()


def generator(chunks: list[Chunk]) -> OpenAIGenerator:
    """A real OpenAIGenerator with a stand-in SDK behind it."""
    built = OpenAIGenerator(api_key="not-a-key", model="fake-model")
    built._client = StubClient(chunks)  # type: ignore[assignment]
    return built


# --- what the stream produces ------------------------------------------------


def test_the_pieces_join_into_the_completion_at_the_end() -> None:
    pieces = list(
        generator([text_chunk("The wall "), text_chunk("went up [1].")]).stream([])
    )

    assert pieces[:-1] == ["The wall ", "went up [1]."]
    assert isinstance(pieces[-1], Completion)
    assert pieces[-1].text == "The wall went up [1]."


def test_the_clock_does_not_start_on_a_leading_blank_line() -> None:
    """A newline is not an answer arriving, and starting the clock on one would
    flatter the number this whole phase is measured by.
    """
    pieces = list(generator([text_chunk("\n\n"), text_chunk("Berlin [1].")]).stream([]))

    assert pieces[0] == "Berlin [1]."
    assert isinstance(pieces[-1], Completion)
    assert pieces[-1].first_token_ms is not None


def test_the_token_counts_come_out_of_the_final_usage_chunk() -> None:
    """The named risk in D-095: without these the eval's only price goes blank
    and nothing fails.
    """
    pieces = list(
        generator(
            [text_chunk("Berlin [1]."), Chunk(choices=[], usage=Usage(2629, 178))]
        ).stream([])
    )

    assert isinstance(pieces[-1], Completion)
    assert (pieces[-1].prompt_tokens, pieces[-1].completion_tokens) == (2629, 178)


def test_usage_is_asked_for_explicitly() -> None:
    """A streamed call reports nothing unless it is requested."""
    built = generator([text_chunk("Berlin [1].")])
    list(built.stream([]))

    assert built._client.chat.completions.kwargs["stream_options"] == {  # type: ignore[attr-defined]
        "include_usage": True
    }


def test_a_stream_with_no_text_in_it_is_a_failure_not_an_empty_answer() -> None:
    with pytest.raises(GenerationUnavailable):
        list(generator([text_chunk(None), text_chunk("")]).stream([]))


def test_the_empty_reply_is_still_the_exception_the_answer_path_catches() -> None:
    """`EmptyCompletion` must stay a `GenerationUnavailable`, and this is why.

    The claim splitter needs to tell "nothing, as instructed" apart from "the
    model fell over", so the empty case got its own class. Every other caller --
    `/ask`, the eval runner, the verifier -- catches `GenerationUnavailable` and
    must keep catching this. If the subclass relationship is ever broken, an
    empty reply stops being handled and starts being a 500.

    This is also the whole argument that D-089's gate is not owed for that
    change: the answer path's behaviour is identical, and it is identical by a
    property a test can hold rather than by inspection. D-102.
    """
    assert issubclass(EmptyCompletion, GenerationUnavailable)
    with pytest.raises(EmptyCompletion):
        list(generator([text_chunk("")]).stream([]))


def test_an_sdk_error_becomes_the_one_exception_callers_know_about() -> None:
    class Failing(StubCompletions):
        def create(self, **kwargs: object) -> Iterator[Chunk]:
            raise APIConnectionError(request=None)  # type: ignore[arg-type]

    built = OpenAIGenerator(api_key="not-a-key", model="fake-model")
    built._client = type(
        "C", (), {"chat": type("Chat", (), {"completions": Failing([])})()}
    )()

    with pytest.raises(GenerationUnavailable):
        list(built.stream([]))


# --- the loop written once ---------------------------------------------------


def test_complete_returns_the_whole_answer_and_drops_the_pieces() -> None:
    assert complete(FakeGenerator(answer="Berlin [1]."), []).text == "Berlin [1]."
