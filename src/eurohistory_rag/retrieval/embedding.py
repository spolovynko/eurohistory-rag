"""Turning text into vectors.

The only place an embedding model is chosen. Both the offline indexing job and
the online /search path go through here, which is what guarantees that queries
and documents land in the same vector space -- if they did not, retrieval would
return plausible-looking nonsense with no error anywhere.
"""

from collections.abc import Sequence
from typing import Protocol

from openai import OpenAI

# One request carries many texts. The API caps both the number of inputs and
# the total tokens; 256 chunks of ~300 tokens sits well inside both, and keeps
# a failed request cheap to retry.
MAX_TEXTS_PER_REQUEST = 256

# The SDK retries 429s and 5xx itself with exponential backoff, so there is no
# hand-rolled retry loop here.
MAX_RETRIES = 5


class Embedder(Protocol):
    """Text in, vectors out.

    Deliberately two members: callers need to embed, and the vector store needs
    to know how wide the vectors are so it can create a matching collection.
    Anything else belongs to the implementation.
    """

    @property
    def dimensions(self) -> int:
        """Length of every vector this embedder returns."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in the same order."""
        ...


class OpenAIEmbedder:
    """Embedder backed by the OpenAI embeddings API."""

    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self._client = OpenAI(api_key=api_key, max_retries=MAX_RETRIES)
        self._model = model
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        """Length of every vector this embedder returns."""
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed one request's worth of texts, in order.

        Batching is the caller's job, not this method's: the indexing job has
        to checkpoint per batch anyway, and two layers of batching in different
        files would make the real batch size impossible to reason about.
        """
        if not texts:
            return []
        if len(texts) > MAX_TEXTS_PER_REQUEST:
            raise ValueError(
                f"{len(texts)} texts in one request; the limit is "
                f"{MAX_TEXTS_PER_REQUEST}. Batch before calling."
            )

        response = self._client.embeddings.create(
            model=self._model,
            input=list(texts),
            dimensions=self._dimensions,
        )

        # Sorted by index rather than trusted to arrive in order: a silently
        # reordered response would attach every vector to the wrong chunk, and
        # nothing downstream could detect it.
        vectors = [
            item.embedding for item in sorted(response.data, key=lambda d: d.index)
        ]

        if len(vectors[0]) != self._dimensions:
            raise ValueError(
                f"{self._model} returned {len(vectors[0])}-dim vectors, "
                f"expected {self._dimensions}. Check EMBEDDING_DIMENSIONS."
            )
        return vectors
