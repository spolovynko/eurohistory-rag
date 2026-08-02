"""Test doubles used across the suite.

`FakeEmbedder` is the second implementation of `Embedder` that justifies the
Protocol existing at all: it makes every test that touches embedding run with
no network, no API key and no cost.
"""

from collections.abc import Sequence

# A tiny fixed vocabulary. Real embeddings come from a trained model; these come
# from counting words, which is enough to give texts sharing words a similar
# direction and texts sharing none an unrelated one.
VOCABULARY = (
    "marshall",
    "plan",
    "berlin",
    "blockade",
    "treaty",
    "rome",
    "wall",
    "cold",
)


class FakeEmbedder:
    """An Embedder backed by word counts instead of a model."""

    def __init__(self, vocabulary: Sequence[str] = VOCABULARY) -> None:
        self._vocabulary = tuple(vocabulary)
        self.calls: list[list[str]] = []

    @property
    def dimensions(self) -> int:
        """One slot per vocabulary word, plus the constant tail."""
        return len(self._vocabulary) + 1

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, recording the call so tests can inspect it."""
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        """Word counts, with a constant 1.0 on the end.

        The constant keeps the vector non-zero: cosine distance is undefined for
        an all-zero vector, and a test text using none of the vocabulary would
        otherwise produce one.
        """
        words = text.lower().split()
        return [*(float(words.count(term)) for term in self._vocabulary), 1.0]
