"""Tests for the streaming model client.

Nothing here reaches OpenAI. The SDK object is replaced with a stand-in that
yields the chunk shapes the real one yields, because what is being checked is
our handling of them -- where the clock starts, where the token counts come
from, and what an empty stream becomes.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from openai import APIConnectionError

from eurohistory_rag.core.spend import CeilingExceeded, Ledger, Meter, dollars
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
class PromptTokensDetails:
    cached_tokens: int


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
    # Optional in the SDK and absent on providers that do not cache, which is
    # why the loop must not assume it is there. D-103.
    prompt_tokens_details: PromptTokensDetails | None = None


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
        # How many times the SDK was actually reached. Added in Phase 30: the
        # cost ceiling's whole claim is that a refusal happens before this
        # number moves, and "it raised" does not say that. D-104.
        self.calls = 0

    def create(self, **kwargs: object) -> Iterator[Chunk]:
        self.kwargs = kwargs
        self.calls += 1
        return iter(self._chunks)


class StubClient:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.completions = StubCompletions(chunks)
        self.chat = type("Chat", (), {"completions": self.completions})()


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
            [
                text_chunk("Berlin [1]."),
                Chunk(
                    choices=[],
                    usage=Usage(2629, 178, PromptTokensDetails(cached_tokens=1664)),
                ),
            ]
        ).stream([])
    )

    assert isinstance(pieces[-1], Completion)
    assert (pieces[-1].prompt_tokens, pieces[-1].completion_tokens) == (2629, 178)
    assert pieces[-1].cached_tokens == 1664


def test_a_provider_that_reports_no_cache_detail_leaves_cached_tokens_none() -> None:
    """None means "nobody said", and it must not become a zero.

    A zero would read as "this call paid full price for every token", which is a
    claim about money the response never made. D-103.
    """
    pieces = list(
        generator(
            [text_chunk("Berlin [1]."), Chunk(choices=[], usage=Usage(2629, 178))]
        ).stream([])
    )

    assert isinstance(pieces[-1], Completion)
    assert pieces[-1].cached_tokens is None


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


# --- the cost ceiling --------------------------------------------------------


def usage_chunk(prompt: int, cached: int, completion: int) -> Chunk:
    """The final chunk, carrying counts and no text."""
    return Chunk(
        choices=[],
        usage=Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            prompt_tokens_details=PromptTokensDetails(cached_tokens=cached),
        ),
    )


def metered(chunks: list[Chunk], ledger: Ledger, ceiling: float) -> OpenAIGenerator:
    """A real generator over a stand-in SDK, with a meter attached."""
    built = OpenAIGenerator(
        api_key="not-a-key",
        model="gpt-4.1-mini",
        meter=Meter(ledger=ledger, day_ceiling=ceiling),
    )
    built._client = StubClient(chunks)  # type: ignore[assignment]
    return built


def test_the_real_client_refuses_before_it_reaches_the_sdk(tmp_path: Path) -> None:
    """A maxed-out day stops `OpenAIGenerator` inside its own `stream`.

    The same claim `tests/core/test_spend.py` makes about the meter, made here
    against the class that actually spends -- and the stand-in SDK is the proof.
    If the ceiling were checked anywhere after the request were built, `calls`
    would read 1. It is the phase's done-when at the one place money leaves.
    """
    ledger = Ledger(tmp_path / "spend")
    ledger.record(5.00, "gpt-4.1-mini")
    built = metered([text_chunk("never asked")], ledger, 1.00)

    with pytest.raises(CeilingExceeded):
        list(built.stream([]))

    assert built._client.completions.calls == 0  # type: ignore[attr-defined]


def test_a_completed_call_is_added_to_the_day(tmp_path: Path) -> None:
    """Under the ceiling the call goes through and the ledger moves.

    The pair to the test above: together they say the meter is wired into the
    real client rather than merely defined next to it.
    """
    ledger = Ledger(tmp_path / "spend")
    built = metered([text_chunk("an answer"), usage_chunk(1000, 0, 100)], ledger, 1.00)

    complete(built, [])

    assert ledger.today().calls == 1
    assert ledger.today().dollars == pytest.approx(
        dollars(1000, 0, 100, "gpt-4.1-mini")
    )


def test_a_stream_that_dies_partway_is_still_charged(tmp_path: Path) -> None:
    """A broken stream is billed by the provider, so it is billed here.

    The recording sits in a `finally` for this reason. A ledger that only
    counted clean successes would let a loop of failures spend without the
    total ever moving -- which is exactly the shape this phase exists to notice.
    """
    ledger = Ledger(tmp_path / "spend")
    built = metered([usage_chunk(1000, 0, 100)], ledger, 1.00)

    with pytest.raises(EmptyCompletion):
        complete(built, [])

    assert ledger.today().calls == 1


def test_an_unmetered_generator_still_works(tmp_path: Path) -> None:
    """No meter means no ceiling and no ledger, which is what the fakes get."""
    pieces = list(generator([text_chunk("fine")]).stream([]))
    assert pieces[0] == "fine"
