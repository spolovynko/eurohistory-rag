"""The embedder: its guards, and the promise it makes about ordering.

Nothing here reaches the network. What OpenAI returns for a given text is their
concern; what this module does with the response is ours.
"""

from typing import Any

import pytest

from eurohistory_rag.retrieval.embedding import (
    MAX_TEXTS_PER_REQUEST,
    Embedder,
    OpenAIEmbedder,
)
from tests.fakes import FakeEmbedder

# --- helpers ----------------------------------------------------------------


class _StubItem:
    """One entry of an embeddings response."""

    def __init__(self, index: int, embedding: list[float]) -> None:
        self.index = index
        self.embedding = embedding


class _StubResponse:
    def __init__(self, data: list[_StubItem]) -> None:
        self.data = data


class _StubEmbeddings:
    """Stands in for `client.embeddings`, answering in reverse order on purpose."""

    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors

    def create(self, **_: Any) -> _StubResponse:
        items = [_StubItem(index, vec) for index, vec in enumerate(self._vectors)]
        return _StubResponse(list(reversed(items)))


class _StubClient:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.embeddings = _StubEmbeddings(vectors)


def embedder_with(vectors: list[list[float]], dimensions: int) -> OpenAIEmbedder:
    """A real OpenAIEmbedder with its OpenAI client swapped for a stub.

    The private attribute is reached into deliberately: the alternative is a
    constructor argument that exists only for tests, and this keeps the seam in
    the test rather than in the production signature.
    """
    embedder = OpenAIEmbedder(api_key="test", model="test-model", dimensions=dimensions)
    embedder._client = _StubClient(vectors)  # type: ignore[assignment]
    return embedder


# --- the Protocol -----------------------------------------------------------


def test_the_fake_satisfies_the_embedder_protocol() -> None:
    """Checked by mypy at the annotation, and at runtime by using it."""
    embedder: Embedder = FakeEmbedder()
    vectors = embedder.embed(["Marshall Plan"])
    assert len(vectors) == 1
    assert len(vectors[0]) == embedder.dimensions


def test_the_fake_puts_shared_words_in_a_shared_direction() -> None:
    """What makes the fake usable for search tests rather than only shape tests."""
    embedder = FakeEmbedder()
    marshall, also_marshall, berlin = embedder.embed(
        ["Marshall plan aid", "the Marshall plan", "Berlin wall"]
    )
    assert marshall[:2] == also_marshall[:2]
    assert marshall[:2] != berlin[:2]


# --- guards -----------------------------------------------------------------


def test_no_texts_means_no_request() -> None:
    embedder = OpenAIEmbedder(api_key="unused", model="m", dimensions=4)
    assert embedder.embed([]) == []


def test_more_texts_than_one_request_allows_is_refused() -> None:
    embedder = OpenAIEmbedder(api_key="unused", model="m", dimensions=4)
    with pytest.raises(ValueError, match="Batch before calling"):
        embedder.embed(["text"] * (MAX_TEXTS_PER_REQUEST + 1))


def test_a_wrongly_sized_vector_is_refused() -> None:
    """A model whose real width is not the configured one fails here, loudly.

    Left uncaught it surfaces much later as a Qdrant dimension error, or not at
    all if the collection happens to have been created from the same wrong
    number.
    """
    embedder = embedder_with([[0.0, 1.0]], dimensions=4)
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS"):
        embedder.embed(["one text"])


# --- ordering ---------------------------------------------------------------


def test_vectors_come_back_in_the_order_the_texts_went_in() -> None:
    """The stub answers backwards on purpose.

    Nothing downstream could detect a reordered response -- every vector would
    simply be attached to the wrong chunk -- so this is the one property of the
    embedder worth a test of its own.
    """
    embedder = embedder_with([[1.0, 0.0], [0.0, 1.0]], dimensions=2)
    assert embedder.embed(["first", "second"]) == [[1.0, 0.0], [0.0, 1.0]]
